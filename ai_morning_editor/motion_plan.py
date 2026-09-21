"""Deterministic research.json to intel-board motion plan.

The editor already owns what a story says; this module owns how it is shown.
Nothing here calls a model: story-to-board routing, emphasis, number
extraction, pacing and timeline alignment are all reproducible, so the same
research.json always yields the same board set.

Timeline sources, in priority order:
  1. a real ``script.srt`` (Whisper or TTS timestamps) when one is present;
  2. otherwise a deterministic reading-speed estimate, with a warning.

Boards render through ``motion.intel_board`` with ``motion_style`` set to
``intel_board``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


STYLE = "intel_board"
CHARS_PER_SECOND = 4.6          # measured against the 2026-09-18 narration
MIN_BOARD_SECONDS = 4.0
MAX_BOARD_SECONDS = 12.0
TARGET_BOARD_SECONDS = 11.0

SRT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*"
    + r"-{1,2}>[\s]*"
    + r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)
NUMBER_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*"
    r"(%|％|美元|元|亿元|亿|万元|万|个月|月|年|天|小时|分钟|条|个|家|名|人|倍|座席)"
)
ACCENT_MARKERS = ("不是", "而非", "却", "反而", "其实", "真正", "关键", "门槛", "静默失败")
RISK_MARKERS = ("风险", "隐患", "存疑", "不确定", "尚未", "但是", "限制", "削弱", "门槛", "为时过早")
OPPORTUNITY_MARKERS = ("机会", "降低", "提升", "增加", "成本", "收入", "基准", "理由", "付费")
ENUM_SPLIT = re.compile(r"\s*(?:、|；|;)\s*")


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_srt(text: str) -> list[dict]:
    """Parse SRT text into a list of ``{start, end, text}`` cues."""
    cues = []
    for block in re.split(r"\r?\n\r?\n+", str(text or "")):
        match = SRT_TIME.search(block)
        if not match:
            continue
        parts = [int(value) for value in match.groups()]
        start = parts[0] * 3600 + parts[1] * 60 + parts[2] + parts[3] / 1000
        end = parts[4] * 3600 + parts[5] * 60 + parts[6] + parts[7] / 1000
        body = _clean(block[match.end():].replace("\n", " "))
        if body:
            cues.append({"start": round(start, 3), "end": round(end, 3), "text": body})
    return cues


def extract_numbers(*values) -> list[dict]:
    """Pull headline figures with their unit; deterministic and ordered."""
    seen, result = set(), []
    for value in values:
        for raw, unit in NUMBER_RE.findall(_clean(value)):
            key = f"{raw}{unit}"
            if key in seen:
                continue
            seen.add(key)
            result.append({"value": key, "raw": float(raw), "unit": unit})
    return result


def jitter_range(value: float, unit: str) -> list[int]:
    """Plausible jitter band so a counter settles instead of snapping."""
    if unit in ("%", "％"):
        return [max(1, int(value * 0.35)), max(6, int(value * 1.9))]
    if value <= 1:
        return [1, 9]
    return [max(1, int(value * 0.25)), max(4, int(value * 2.4))]


def format_title(title: str) -> str:
    """Two-line headline with one accent when the claim has one."""
    text = _clean(title).rstrip("。.!！?？")
    # A colon is an explicit editorial split, so short heads are fine there;
    # commas need more room or the two lines read as fragments.
    for mark, min_head in (("：", 2), (":", 2), ("——", 2), ("，", 5), (",", 5)):
        if mark in text:
            head, tail = text.split(mark, 1)
            if min_head <= len(head) <= 22 and 3 <= len(tail) <= 24:
                text = f"{head}|{tail}"
                break
    else:
        if len(text) > 14:
            split = len(text) // 2
            text = f"{text[:split]}|{text[split:]}"
    if any(marker in text for marker in ACCENT_MARKERS):
        parts = text.split("|")
        parts[-1] = f"*{parts[-1]}*"
        text = "|".join(parts)
    return text


def enumerable_items(*values, limit: int = 4) -> list[str]:
    """Rows for a list board, only when the source really enumerates."""
    for value in values:
        parts = [part.strip("。.! ") for part in ENUM_SPLIT.split(_clean(value))]
        parts = [part for part in parts if 2 <= len(part) <= 22]
        if len(parts) >= 2:
            return parts[:limit]
    return []


def _has(text: str, markers) -> bool:
    return any(marker in text for marker in markers)


def _confidence(story: dict) -> float:
    """Confidence as a number; unparsable values fall back to 'trusted'."""
    try:
        return float(story.get("confidence"))
    except (TypeError, ValueError):
        return 1.0


UNIT_LABELS = {
    "%": "百分比口径", "％": "百分比口径", "美元": "美元口径", "元": "元口径",
    "亿": "亿规模", "亿元": "亿元规模", "万": "万规模", "万元": "万元规模",
    "名": "涉及人数", "人": "涉及人数", "个": "数量", "条": "样本条数",
    "家": "企业数量", "月": "个月周期", "个月": "个月周期", "年": "年周期",
    "天": "天周期", "小时": "小时周期", "分钟": "分钟周期", "倍": "倍数变化",
    "座席": "每座席口径",
}


def _unit_label(unit: str) -> str:
    return UNIT_LABELS.get(unit, f"{unit}口径")


def _eyebrow(segment: str) -> dict:
    return {"left": "", "center": "AI 商业晨报", "right": segment}


def story_board_specs(story: dict, index: int, total: int) -> list[dict]:
    """Route one story to boards. Deterministic: same story, same boards."""
    title = _clean(story.get("title"))
    summary = _clean(story.get("summary"))
    impact = _clean(story.get("business_impact"))
    body = f"{summary} {impact}"
    label = f"第{'一二三四五六'[min(index, 5)]}条" if index < 6 else f"第{index + 1}条"
    source = _clean(story.get("source_name")) or "来源未标注"

    specs = [{
        "template": "M_TITLE",
        "weight": 0.30,
        "props": {
            "template": "M_TITLE",
            "eyebrow": _eyebrow(label),
            "title": format_title(title),
            "subtitle": source,
        },
    }]

    numbers = extract_numbers(summary, impact)
    if numbers:
        # One board carries up to three figures side by side. Splitting them
        # into one board per number produced near-identical frames in a row.
        specs.append({
            "template": "M_NUMBER",
            "weight": 0.34,
            "props": {
                "template": "M_NUMBER",
                "eyebrow": _eyebrow(label),
                "title": format_title(title),
                "numbers": [
                    {
                        "value": item["value"],
                        "label": _unit_label(item["unit"]),
                        "accent": position == 0,
                        "jitter": jitter_range(item["raw"], item["unit"]),
                    }
                    for position, item in enumerate(numbers[:3])
                ],
                "subtitle": _clean(story.get("source_name")),
            },
        })

    risk = _has(impact, RISK_MARKERS)
    upside = _has(impact, OPPORTUNITY_MARKERS)
    if risk and upside:
        specs.append({
            "template": "M_COMPARE",
            "weight": 0.30,
            "props": {
                "template": "M_COMPARE",
                "eyebrow": _eyebrow(label),
                "title": format_title(title),
                "axis": "columns",
                "accent_side": 1,
                "columns": [
                    {"heading": "可能的机会", "body": impact[:70]},
                    {"heading": "需要留意", "body": impact[70:150] or summary[:70]},
                ],
                "footnote": "需要继续观察" if _confidence(story) < 0.8 else "",
            },
        })
    else:
        items = enumerable_items(impact, summary)
        if items:
            specs.append({
                "template": "M_LIST",
                "weight": 0.30,
                "props": {
                    "template": "M_LIST",
                    "eyebrow": _eyebrow(label),
                    "title": format_title(title),
                    "items": items,
                    "bullet": True,
                },
            })

    takeaway = next(
        (sentence.strip() for sentence in re.split(r"[。！？!?]", impact) if 10 <= len(sentence.strip()) <= 30),
        "",
    )
    if takeaway:
        specs.append({
            "template": "M_TITLE",
            "weight": 0.26,
            "props": {
                "template": "M_TITLE",
                "eyebrow": _eyebrow(label),
                "title": format_title(takeaway),
                "subtitle": f"{source} · 本期判断",
            },
        })
    return specs


def select_specs(specs: list[dict], span: float) -> list[dict]:
    """Keep the plan dense enough for the narration it has to cover."""
    if not specs:
        return []
    wanted = max(1, min(len(specs), round(span / TARGET_BOARD_SECONDS)))
    return specs[:wanted]


def opening_spec(story: dict | None) -> dict:
    if not story:
        return {
            "template": "M_TITLE",
            "weight": 1.0,
            "props": {
                "template": "M_TITLE",
                "eyebrow": _eyebrow("开场"),
                "title": "今天没有足够可靠的商业事件",
            },
        }
    numbers = extract_numbers(story.get("summary"), story.get("business_impact"))
    props = {
        "template": "M_TITLE",
        "eyebrow": _eyebrow("开场"),
        "title": format_title(_clean(story.get("title"))),
        "subtitle": _clean(story.get("source_name")),
    }
    if numbers:
        props["numbers"] = [
            {
                "value": item["value"],
                "label": f"{item['unit']}口径",
                "accent": item is numbers[0],
                "jitter": jitter_range(item["raw"], item["unit"]),
            }
            for item in numbers[:2]
        ]
    return {"template": "M_TITLE", "weight": 1.0, "props": props}


def closing_spec(research: dict) -> dict:
    stories = research.get("stories") or []
    numbers = extract_numbers(*[
        f"{story.get('summary', '')} {story.get('business_impact', '')}" for story in stories[:2]
    ])
    props = {
        "template": "M_TITLE",
        "eyebrow": _eyebrow("收束"),
        "title": "真正要看的是|*这些东西能不能站住*",
    }
    if numbers:
        props["numbers"] = [
            {
                "value": item["value"],
                "label": f"{item['unit']}口径",
                "accent": False,
                "jitter": jitter_range(item["raw"], item["unit"]),
            }
            for item in numbers[:2]
        ]
    return {"template": "M_TITLE", "weight": 1.0, "props": props}


def _anchors(story: dict) -> list[str]:
    title = _clean(story.get("title"))
    latin = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{2,}", title)]
    chinese = re.findall(r"[\u4e00-\u9fff]{2,4}", title)
    return [token for token in latin + chinese if len(token) >= 2]


def align_stories(cues: list[dict], stories: list[dict], script: str) -> tuple[list[tuple[float, float]], list[str]]:
    """Return one (start, end) span per story plus any warnings."""
    warnings: list[str] = []
    if not stories:
        return [], warnings
    if cues:
        starts: list[int] = []
        for story in stories:
            anchors = _anchors(story)
            best_index, best_score = -1, 0
            for index, cue in enumerate(cues):
                score = sum(1 for token in anchors if token in cue["text"])
                if score > best_score:
                    best_index, best_score = index, score
            starts.append(best_index)
        if all(index >= 0 for index in starts) and starts == sorted(starts) and len(set(starts)) == len(starts):
            spans = []
            for position, start_index in enumerate(starts):
                end_index = starts[position + 1] - 1 if position + 1 < len(starts) else len(cues) - 1
                end_index = max(end_index, start_index)
                spans.append((cues[start_index]["start"], cues[end_index]["end"]))
            return spans, warnings
        warnings.append("口播稿与选题标题未能可靠对齐，已按篇幅比例估算时间轴。")

    total = sum(len(_clean(s.get("title")) + _clean(s.get("summary")) + _clean(s.get("business_impact")))
                for s in stories) or 1
    duration = max(30.0, len(_clean(script)) / CHARS_PER_SECOND) if script else 60.0
    spans, cursor = [], 0.0
    for story in stories:
        share = (len(_clean(story.get("title")) + _clean(story.get("summary"))
                     + _clean(story.get("business_impact"))) / total) * duration
        spans.append((round(cursor, 3), round(cursor + share, 3)))
        cursor += share
    return spans, warnings


def build_plan(research: dict, script: str = "", srt_text: str | None = None) -> dict:
    """Turn one research.json into a renderable intel-board plan."""
    stories = [s for s in (research.get("stories") or []) if isinstance(s, dict)]
    cues = parse_srt(srt_text) if srt_text else []
    spans, warnings = align_stories(cues, stories, script)
    timeline_source = "srt" if cues and not warnings else "estimate"

    boards: list[dict] = []
    total_start = cues[0]["start"] if cues else (spans[0][0] if spans else 0.0)
    total_end = cues[-1]["end"] if cues else (spans[-1][1] if spans else 60.0)
    total = max(1.0, total_end - total_start)

    # The cold open and the closing claim need their own slot. Carve both off
    # the ends, then rescale the story spans into the remaining window so the
    # whole plan still tiles the narration exactly once.
    if stories:
        open_len = min(MAX_BOARD_SECONDS, max(MIN_BOARD_SECONDS, total * 0.05))
        close_len = min(MAX_BOARD_SECONDS, max(MIN_BOARD_SECONDS, total * 0.06))
    else:
        open_len = close_len = 0.0
    content_start = total_start + open_len
    content_end = max(content_start + MIN_BOARD_SECONDS, total_end - close_len)
    if spans:
        source_start, source_end = spans[0][0], spans[-1][1]
        source_span = max(0.001, source_end - source_start)
        target_span = content_end - content_start
        spans = [
            (content_start + (begin - source_start) / source_span * target_span,
             content_start + (end - source_start) / source_span * target_span)
            for begin, end in spans
        ]

    def add(spec: dict, start: float, end: float, story_index, board_id, segment="开场"):
        begin = round(max(total_start, start), 3)
        finish = round(max(begin + MIN_BOARD_SECONDS, end), 3)
        props = dict(spec["props"])
        props["duration"] = round(finish - begin, 3)
        boards.append({
            "id": board_id,
            "story_index": story_index,
            "segment": segment,
            "template": spec["template"],
            "start": begin,
            "end": finish,
            "duration": round(finish - begin, 3),
            "props": props,
        })

    if stories and open_len >= MIN_BOARD_SECONDS:
        add(opening_spec(stories[0]), total_start, content_start, None, "B000", "开场")
    elif stories:
        warnings.append("开场时长不足，首条选题直接承担开场命题。")

    for index, story in enumerate(stories):
        span_start, span_end = spans[index]
        specs = select_specs(story_board_specs(story, index, len(stories)), span_end - span_start)
        total_weight = sum(spec["weight"] for spec in specs) or 1.0
        cursor = span_start
        for position, spec in enumerate(specs):
            share = (span_end - span_start) * (spec["weight"] / total_weight)
            add(spec, cursor, cursor + share, index,
                f"B{index + 1:03d}-{position + 1}",
                f"第{'一二三四五六'[min(index, 5)] if index < 6 else index + 1}条")
            cursor += share

    if stories and close_len >= MIN_BOARD_SECONDS:
        add(closing_spec(research), content_end, total_end, None, "B900", "收束")
    elif stories:
        warnings.append("收束时长不足，本期不单独成板。")
    if not stories:
        add(opening_spec(None), total_start, total_end, None, "B000", "开场")

    return {
        "date": research.get("date"),
        "style": STYLE,
        "timeline_source": timeline_source,
        "total_seconds": round(total_end, 3),
        "story_count": len(stories),
        "board_count": len(boards),
        "warnings": warnings,
        "boards": boards,
    }


def to_shots(plan: dict) -> list[dict]:
    """Shot dicts ready for motion.intel_board or the SceneFlow resolver."""
    shots = []
    for board in plan.get("boards") or []:
        shots.append({
            "id": board["id"],
            "visual_role": "M",
            "motion_type": board["template"],
            "motion_style": plan.get("style", STYLE),
            "start": board["start"],
            "end": board["end"],
            "title": board["props"].get("title"),
            "motion_data": board["props"],
        })
    return shots


def render_plan(plan: dict, out_dir: Path, size=(720, 1280)) -> list[dict]:
    """Render every board in a plan through the intel-board renderer."""
    from motion.intel_board import render_intel_board_clip

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for shot in to_shots(plan):
        clip, still = render_intel_board_clip(shot, size, out_dir / f"{shot['id']}.mp4")
        rendered.append({
            "id": shot["id"],
            "template": shot["motion_type"],
            "duration": round(shot["end"] - shot["start"], 3),
            "clip": str(clip),
            "preview": str(still),
        })
    return rendered


def load_inputs(folder: Path) -> tuple[dict, str, str | None]:
    folder = Path(folder)
    research = json.loads((folder / "research.json").read_text(encoding="utf-8"))
    script_path = folder / "script.md"
    script = script_path.read_text(encoding="utf-8") if script_path.is_file() else ""
    srt_path = folder / "script.srt"
    srt_text = srt_path.read_text(encoding="utf-8") if srt_path.is_file() else None
    return research, script, srt_text


def write_plan(folder: Path, research: dict, script: str, srt_text: str | None = None) -> dict:
    plan = build_plan(research, script, srt_text)
    target = Path(folder) / "motion-plan.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="由 research.json 生成情报板动效计划")
    parser.add_argument("folder", nargs="?", default=str(Path(__file__).resolve().parent / "history"))
    parser.add_argument("--print", action="store_true", help="只打印计划，不写文件")
    parser.add_argument("--render", metavar="DIR", help="把每块板渲染成 mp4 到这个目录")
    parser.add_argument("--size", default="720x1280", help="渲染尺寸，默认 720x1280")
    args = parser.parse_args(argv)
    folder = Path(args.folder)
    research, script, srt_text = load_inputs(folder)
    plan = build_plan(research, script, srt_text)
    if args.print:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        write_plan(folder, research, script, srt_text)
        print(f"{folder / 'motion-plan.json'}  {plan['board_count']} 板 / "
              f"{plan['total_seconds']}s / 时间轴={plan['timeline_source']}")
        for warning in plan["warnings"]:
            print("  提示：" + warning)
        if args.render:
            width, _, height = args.size.partition("x")
            rendered = render_plan(plan, Path(args.render), (int(width), int(height)))
            print(f"已渲染 {len(rendered)} 块板到 {Path(args.render)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
