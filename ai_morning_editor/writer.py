"""Select stories and write Scene Flow-ready Chinese narration."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import requests


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"


def load_llm_config(settings_path: Path | None = None) -> dict | None:
    api_key = os.environ.get("MORNING_LLM_API_KEY", "").strip()
    base_url = os.environ.get("MORNING_LLM_BASE_URL", "").strip()
    model = os.environ.get("MORNING_LLM_MODEL", "").strip()
    source = "environment"
    if not api_key and settings_path and settings_path.is_file():
        try:
            saved = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        api_key = str(saved.get("llm_api_key") or "").strip()
        provider = str(saved.get("llm_provider") or "deepseek").strip()
        if provider == "custom":
            base_url = str(saved.get("llm_custom_base_url") or "").strip()
            model = str(saved.get("llm_custom_model") or "").strip()
        else:
            base_url, model = DEFAULT_BASE_URL, DEFAULT_MODEL
        source = "Scene Flow private settings"
    if not api_key:
        return None
    return {
        "api_key": api_key,
        "base_url": (base_url or DEFAULT_BASE_URL).rstrip("/"),
        "model": model or DEFAULT_MODEL,
        "source": source,
    }


def _parse_json_reply(value: str) -> dict:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("model returned empty content")
    text = value.strip().lstrip("\ufeff")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as original:
        # Some compatible APIs still wrap JSON in a short preface even when
        # response_format=json_object is requested. Decode the first complete
        # object instead of sending an otherwise good Chinese briefing to the
        # unsafe deterministic fallback.
        decoder = json.JSONDecoder()
        payload = None
        for match in re.finditer(r"\{", text):
            try:
                candidate, _ = decoder.raw_decode(text[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
        if payload is None:
            raise original
    if not isinstance(payload, dict):
        raise ValueError("model did not return an object")
    return payload


def _chinese_share(value: str) -> tuple[int, float]:
    chinese = len(re.findall(r"[\u3400-\u9fff]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    return chinese, chinese / max(1, chinese + latin)


def _has_english_sentence(value: str) -> bool:
    return bool(re.search(r"(?:\b[A-Za-z][A-Za-z0-9'./+-]*\b[\s,;:()\-]+){6,}\b[A-Za-z][A-Za-z0-9'./+-]*\b", value))


def _validate_chinese_output(selected: list[dict], script: str) -> None:
    """Reject English source copy while allowing product names such as OpenAI."""
    script_chinese, script_share = _chinese_share(script)
    if script_chinese < 80 or script_share < 0.62 or _has_english_sentence(script):
        raise ValueError("model script is not predominantly Chinese")
    for story in selected:
        title_chinese, _ = _chinese_share(story["title"])
        summary_chinese, summary_share = _chinese_share(story["summary"])
        impact_chinese, impact_share = _chinese_share(story["business_impact"])
        if title_chinese < 2:
            raise ValueError("model story title is not Chinese")
        if summary_chinese < 12 or summary_share < 0.35 or _has_english_sentence(story["summary"]):
            raise ValueError("model story summary is not predominantly Chinese")
        if impact_chinese < 12 or impact_share < 0.35 or _has_english_sentence(story["business_impact"]):
            raise ValueError("model story impact is not predominantly Chinese")


def _call_model(config: dict, candidates: list[dict], max_stories: int) -> dict:
    evidence = []
    for index, item in enumerate(candidates):
        evidence.append({
            "candidate_index": index,
            "title": item["title"],
            "published_at": item["published_at"],
            "source_name": item["source_name"],
            "source_tier": item["source_tier"],
            "verified": item["verified"],
            "confidence": item["confidence"],
            "rank_score": item["rank_score"],
            "feed_summary": item.get("summary", ""),
            "page_evidence": item.get("evidence", "")[:3600],
            "supporting_sources": item.get("supporting_sources", []),
        })
    system = """你是严谨的中文 AI 商业晨报主编。只能使用输入证据，不补写未经证实的数字、引语和因果关系。重点是商业影响，而不是技术热闹。"""
    minimum = min(3, len(candidates))
    prompt = f"""从下面候选中选出 {minimum} 到 {min(max_stories, len(candidates))} 个最值得讲的不同事件。一手来源优先；纯论文、普通补丁版本、纯营销和无商业落地的指标不要入选。宁可只选 3 到 4 条，也不要用弱新闻凑到 5 条。只有证据明确支持近期成本、采购、收入、竞争或知识产权影响时，科研新闻才可入选。

输出严格 JSON：
{{
  "selected": [{{"candidate_index": 0, "title": "中文标题", "summary": "发生了什么，2到3句", "business_impact": "为什么重要、影响谁、实际机会或风险，2到4句"}}],
  "script": "完整中文口播稿"
}}

script 要求：
- 约 1500 到 1900 个中文字符，适合 5 到 7 分钟单人口播。
- 输入证据可以是英文，但标题、摘要、商业影响和口播都要理解后用中文重写；禁止复制完整英文句子。公司名、产品名和缩写可保留原文。
- 开头直接讲今天最值得关注的一件事，禁止“欢迎收看”。
- 正文自然串联 3 到 {max_stories} 条，每条遵循事实→为什么重要→商业影响，但不要念小标题或来源清单。
- 中文口语、简洁、有判断、不夸张，让普通职场人、创业者、AI 从业者听懂。
- 不要把推测说成事实；有不确定性要明确说。
- 结尾只总结一件最值得继续观察的事。

候选证据：
{json.dumps(evidence, ensure_ascii=False)}"""
    last_error: Exception | None = None
    # A model can occasionally return a truncated object even with JSON mode.
    # Three bounded attempts are enough to recover without creating an open-ended loop.
    for attempt in range(3):
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        if attempt:
            messages.append({
                "role": "user",
                "content": "上一次输出无法解析或夹有过多英文。请重新完成任务，只返回一个完整 JSON 对象；标题、摘要、商业影响和口播稿都必须以中文为主。",
            })
        try:
            response = requests.post(
                config["base_url"] + "/chat/completions",
                headers={"Authorization": "Bearer " + config["api_key"], "Content-Type": "application/json"},
                json={
                    "model": config["model"],
                    "messages": messages,
                    "temperature": 0.2 if attempt else 0.25,
                    "max_tokens": 5200,
                    "response_format": {"type": "json_object"},
                    **({"thinking": {"type": "disabled"}} if "deepseek.com" in config["base_url"] else {}),
                },
                timeout=(10, 120),
            )
            response.raise_for_status()
            body = response.json()
            payload = _parse_json_reply(body["choices"][0]["message"]["content"])
            selected, script = _valid_selection(payload, candidates, max_stories)
            _validate_chinese_output(selected, script)
            return payload
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _fallback(candidates: list[dict], max_stories: int) -> dict:
    chosen = candidates[:max_stories]
    selected = []
    paragraphs = []
    for index, item in enumerate(chosen):
        haystack = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        if any(word in haystack for word in ("price", "pricing", "cost", "subscription", "revenue")):
            topic = "人工智能产品的价格、订阅或成本出现新变化"
            impact = "这类变化可能影响企业采购预算、个人订阅选择和相关公司的收入方式，具体影响仍需结合原始价格与适用范围判断。"
        elif any(word in haystack for word in ("security", "attack", "hack", "vulnerability", "guard")):
            topic = "人工智能安全与风险管理出现新动态"
            impact = "这类变化可能影响企业的安全投入、权限管理和供应商选择，后续应关注真实部署效果与责任边界。"
        elif any(word in haystack for word in ("data center", "datacenter", "energy", "poll", "regulation")):
            topic = "人工智能基础设施面临新的成本或监管信号"
            impact = "这类信号可能影响数据中心建设、算力供给和项目审批，企业需要继续观察成本、政策与社会接受度的变化。"
        elif any(word in haystack for word in ("release", "sdk", "api", "developer", "model")):
            topic = "人工智能开发工具或接口发布更新"
            impact = "这类更新可能改变开发效率、接入成本和供应商选择，但是否值得迁移仍要看兼容性、稳定性与实际工作量。"
        else:
            topic = "人工智能商业领域出现一项新动态"
            impact = "它是否会真正改变企业采购、开发成本或收入机会，还要看后续价格、客户采用和实际交付。"
        title = f"晨报候选：{topic}"
        summary = f"过去二十四小时内，可靠来源发布了与“{topic}”有关的消息。自动编辑本次未能产出可信的全中文改写，因此这里不照搬英文原文；具体事实以附带的原始链接为准。"
        selected.append({"candidate_index": index, "title": title, "summary": summary, "business_impact": impact})
        paragraphs.append(f"第{index + 1}条候选与{topic}有关。{summary}{impact}")
    lead = "自动编辑暂时没有产出可直接播出的完整中文稿"
    script = f"今天先说明一个情况：{lead}。系统已经核验了过去二十四小时的可靠来源，但为了避免把英文原文直接塞进中文晨报，也为了避免未经确认的误译，本次降级稿只保留事件类型和原始链接。\n\n" + "\n\n".join(paragraphs)
    script += "\n\n这份内容适合核对线索，不建议未经人工检查直接制作视频。等自动编辑恢复后，应重新生成完整中文口播稿。"
    return {"selected": selected, "script": script, "fallback": True}


def _valid_selection(payload: dict, candidates: list[dict], max_stories: int) -> tuple[list[dict], str]:
    selected = payload.get("selected")
    script = payload.get("script")
    if not isinstance(selected, list) or not isinstance(script, str) or not script.strip():
        raise ValueError("model response is missing selected/script")
    result = []
    used = set()
    for story in selected[:max_stories]:
        if not isinstance(story, dict) or not isinstance(story.get("candidate_index"), int):
            continue
        index = story["candidate_index"]
        if index in used or not (0 <= index < len(candidates)):
            continue
        title = str(story.get("title") or "").strip()
        summary = str(story.get("summary") or "").strip()
        impact = str(story.get("business_impact") or "").strip()
        if not title or not summary or not impact:
            continue
        used.add(index)
        result.append({"candidate_index": index, "title": title, "summary": summary, "business_impact": impact})
    minimum = min(3, len(candidates))
    if len(result) < minimum:
        raise ValueError("model selected too few valid stories")
    return result, script.strip()


def write_briefing(candidates: list[dict], max_stories: int, settings_path: Path | None, use_llm: bool = True) -> tuple[dict, str, list[str]]:
    warnings: list[str] = []
    candidates = [item for item in candidates if float(item.get("rank_score") or 0) >= 3.0]
    if not candidates:
        warnings.append("过去 24 小时没有达到商业价值门槛的可靠事件，没有使用旧闻或弱新闻凑数。")
        return {"date": datetime.now().astimezone().date().isoformat(), "stories": []}, "过去二十四小时没有找到值得占用你时间的 AI 商业事件。今天不为数量凑新闻。", warnings
    payload = None
    config = load_llm_config(settings_path) if use_llm else None
    if config and candidates:
        try:
            payload = _call_model(config, candidates, max_stories)
        except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            warnings.append(f"AI 编辑暂时不可用，已生成可用的降级稿：{type(exc).__name__}")
    elif use_llm:
        warnings.append("未找到晨报模型密钥，已生成可用的降级稿；可配置 MORNING_LLM_API_KEY。")
    else:
        warnings.append("本次未调用 AI 编辑，已生成不照搬英文原文的安全降级稿。")
    if payload is None:
        payload = _fallback(candidates, max_stories)
    try:
        selected, script = _valid_selection(payload, candidates, max_stories)
        _validate_chinese_output(selected, script)
    except ValueError:
        warnings.append("AI 编辑结果结构不完整或中文比例不足，已改用不照搬英文原文的安全降级稿。")
        selected, script = _valid_selection(_fallback(candidates, max_stories), candidates, max_stories)
        _validate_chinese_output(selected, script)

    stories = []
    for edited in selected:
        source = candidates[edited["candidate_index"]]
        story = {
            "title": edited["title"],
            "summary": edited["summary"],
            "business_impact": edited["business_impact"],
            "source_name": source["source_name"],
            "source_url": source["source_url"],
            "published_at": source["published_at"],
            "confidence": source["confidence"],
            "verified": source["verified"],
        }
        if source.get("media_source"):
            story["media_source"] = source["media_source"]
        if source.get("primary_source"):
            story["primary_source"] = source["primary_source"]
        if source.get("supporting_sources"):
            story["supporting_sources"] = source["supporting_sources"]
        stories.append(story)
    return {"date": datetime.now().astimezone().date().isoformat(), "stories": stories}, script, warnings
