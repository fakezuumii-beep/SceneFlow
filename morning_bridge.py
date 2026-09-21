"""Narrow file-based bridge between the morning editor and Scene Flow."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import re
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
EDITOR = ROOT / "ai_morning_editor"
OUTPUT = EDITOR / "output"
HISTORY = EDITOR / "history"
MAX_RESEARCH_BYTES = 2 * 1024 * 1024
MAX_SCRIPT_CHARS = 20_000


def _predominantly_chinese(value: str, minimum: int = 8, share: float = 0.52) -> bool:
    chinese = sum("\u3400" <= char <= "\u9fff" for char in value)
    latin = sum(("a" <= char.lower() <= "z") for char in value)
    english_sentence = re.search(r"(?:\b[A-Za-z][A-Za-z0-9'./+-]*\b[\s,;:()\-]+){6,}\b[A-Za-z][A-Za-z0-9'./+-]*\b", value)
    return chinese >= minimum and chinese / max(1, chinese + latin) >= share and not english_sentence


def _inside(base: Path, relative: str) -> Path:
    value = (ROOT / relative).resolve()
    if not value.is_relative_to(base.resolve()):
        raise ValueError("晨报历史路径无效")
    return value


def _relative(path: Path, base: Path) -> str:
    """POSIX path relative to the workspace, tolerant of path spelling.

    Windows returns 8.3 short names for temporary directories, so a resolved
    path and an unresolved root can name the same folder differently.
    """
    try:
        return Path(path).relative_to(base).as_posix()
    except ValueError:
        return Path(path).resolve().relative_to(Path(base).resolve()).as_posix()


def _http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _source(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    name = str(value.get("source_name") or "").strip()
    url = str(value.get("source_url") or "").strip()
    if not name or not _http_url(url):
        return None
    result = {"source_name": name, "source_url": url}
    if value.get("published_at"):
        result["published_at"] = str(value["published_at"])
    if "verified" in value:
        result["verified"] = bool(value["verified"])
    return result


def read_current() -> dict:
    research_path = OUTPUT / "research.json"
    script_path = OUTPUT / "script.md"
    if not research_path.is_file() or not script_path.is_file():
        return {"ready": False, "message": "今天还没有晨报，请先点击“生成今日晨报”。"}
    if research_path.stat().st_size > MAX_RESEARCH_BYTES:
        raise ValueError("晨报研究文件过大")
    try:
        research_bytes = research_path.read_bytes()
        research = json.loads(research_bytes.decode("utf-8-sig"))
        script_bytes = script_path.read_bytes()
        script = script_bytes.decode("utf-8-sig").strip()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("晨报输出损坏，请重新生成") from exc
    if not isinstance(research, dict) or not isinstance(research.get("stories"), list):
        raise ValueError("research.json 缺少 stories")
    if len(research["stories"]) > 5:
        raise ValueError("晨报最多包含 5 条经过筛选的事件")
    if not script or len(script) > MAX_SCRIPT_CHARS or "\0" in script:
        raise ValueError("script.md 不是可用的 Scene Flow 原稿")
    if not _predominantly_chinese(script, minimum=8, share=0.62):
        raise ValueError("晨报口播稿含有过多英文，请重新生成全中文稿")
    stories = []
    for raw in research["stories"]:
        if not isinstance(raw, dict):
            raise ValueError("晨报事件格式无效")
        title = str(raw.get("title") or "").strip()
        summary = str(raw.get("summary") or "").strip()
        impact = str(raw.get("business_impact") or "").strip()
        if not title or not summary or not impact:
            raise ValueError("晨报事件缺少标题、摘要或商业意义")
        # Titles are allowed to be mostly brand and product names ("Moonshot AI
        # 的 Kimi K3 上线 Amazon Bedrock" is 3 Chinese chars out of 31). The
        # writer prompt explicitly permits keeping those in the original form,
        # so a title only has to prove it is not a pasted English sentence:
        # at least a few Chinese characters, and no long run of English words.
        # Summary and impact keep the stricter share because they carry the
        # argument and must stay readable Chinese.
        if not _predominantly_chinese(title, minimum=2, share=0.05) or not _predominantly_chinese(summary, minimum=5, share=0.35) or not _predominantly_chinese(impact, minimum=5, share=0.35):
            raise ValueError("晨报事件含有过多英文，请重新生成全中文稿")
        primary = _source(raw.get("primary_source"))
        media = _source(raw.get("media_source"))
        legacy = _source(raw)
        if not primary and not media and not legacy:
            raise ValueError("晨报事件缺少可靠来源链接")
        stories.append({
            "title": title,
            "summary": summary,
            "business_impact": impact,
            "confidence": float(raw.get("confidence") or 0),
            "verified": bool(raw.get("verified")),
            "primary_source": primary,
            "media_source": media,
            "source": primary or media or legacy,
        })
    history_path = str(research.get("history_path") or "").strip()
    if history_path:
        history_dir = _inside(HISTORY, history_path)
        if not (history_dir / "research.json").is_file() or not (history_dir / "script.md").is_file():
            raise ValueError("晨报历史快照不完整，请重新生成")
    generation_id = hashlib.sha256(research_bytes + b"\0" + script_bytes).hexdigest()[:20]
    if not stories:
        return {
            "ready": False, "message": "过去 24 小时没有达到商业价值门槛的可靠事件，系统没有用旧闻凑数。",
            "date": str(research.get("date") or ""), "generation_id": generation_id,
        }
    return {
        "ready": True,
        "date": str(research.get("date") or ""),
        "generated_at": str(research.get("generated_at") or ""),
        "window_start": str(research.get("window_start") or ""),
        "window_end": str(research.get("window_end") or ""),
        "history_path": history_path,
        "generation_id": generation_id,
        "stories": stories,
        "script": script,
        "script_chars": len(script),
        "warnings": research.get("warnings") if isinstance(research.get("warnings"), list) else [],
    }


def generate() -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ai_morning_editor"], cwd=ROOT, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("晨报生成超过 5 分钟，已停止等待；旧结果没有被删除") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()[-1200:]
        raise RuntimeError("晨报生成失败：" + (detail or f"退出码 {result.returncode}"))
    return read_current()


def briefing_stories(current: dict) -> list[dict]:
    """Keep each story's own source next to the script it was written from."""
    stories = []
    for story in current.get("stories") or []:
        if not isinstance(story, dict):
            continue
        source = story.get("source") or {}
        stories.append({
            "title": str(story.get("title") or ""),
            "summary": str(story.get("summary") or ""),
            "business_impact": str(story.get("business_impact") or ""),
            "source_name": str(source.get("source_name") or ""),
            "source_url": str(source.get("source_url") or ""),
        })
    return stories


def import_project(core_module, generation_id: str, speaker: str = "zh-CN-XiaoxiaoNeural", speed: float = 1.0) -> tuple[dict, bool]:
    current = read_current()
    if not current.get("ready") or generation_id != current["generation_id"]:
        raise ValueError("晨报内容已经变化，请刷新后重新确认")
    for path in core_module.PROJECTS.glob("*/project.json"):
        try:
            existing = core_module.read_project(path.parent.name)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if existing.get("morning_briefing", {}).get("generation_id") == generation_id:
            return existing, True
    import local_engines
    name = f"AI 商业晨报 · {current['date'] or '今日'}"
    project = core_module.create_project(name)
    project["script"] = local_engines.validate_script({
        "text": current["script"], "provider": "azure-v1", "language": "Chinese",
        "speaker": speaker, "speed": speed,
    })
    project["video_profile"] = "ai_news"
    # The briefing is dense with figures and comparisons, so it renders its
    # motion segments as animated intel boards instead of the static-still
    # default. Only this project opts in; other episodes stay on scene_flow.
    project.setdefault("options", {})["motion_style"] = "intel_board"
    project["morning_briefing"] = {
        "date": current["date"], "generated_at": current["generated_at"],
        "generation_id": generation_id, "history_path": current["history_path"],
        "stories": briefing_stories(current),
    }
    project["revision"] += 1
    core_module.save_project(project)
    return project, False


def archive_final(project: dict, video: Path, export_id: str, kind: str = "final") -> str | None:
    """Copy the episode's final export next to its briefing snapshot.

    Only a final export is archived. A draft export can still carry A-roll
    placeholders, so archiving it first would leave ``final.mp4`` pointing at
    an unfinished cut for the rest of the day.
    """
    if str(kind or "final") != "final":
        return None
    briefing = project.get("morning_briefing")
    if not isinstance(briefing, dict) or not briefing.get("history_path"):
        return None
    history_dir = _inside(HISTORY, str(briefing["history_path"]))
    if not history_dir.is_dir():
        raise ValueError("关联的晨报历史目录不存在")
    target = history_dir / "final.mp4"
    if target.exists():
        def digest(path: Path) -> bytes:
            value = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    value.update(chunk)
            return value.digest()
        if target.stat().st_size == video.stat().st_size and digest(target) == digest(video):
            return _relative(target, ROOT)
        target = history_dir / f"final-{export_id}.mp4"
        if target.exists():
            raise ValueError("晨报历史中的同名成片已经存在")
    shutil.copy2(video, target)
    return _relative(target, ROOT)
