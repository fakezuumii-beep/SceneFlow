"""One-command entry point for the AI business morning editor."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from .collect import collect
from .motion_plan import write_plan
from .rank import rank_and_dedupe
from .verify import verify_candidates
from .writer import write_briefing


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"
DEFAULT_HISTORY = Path(__file__).resolve().parent / "history"
DEFAULT_SETTINGS = ROOT / "data" / "private" / "settings.json"


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def reserve_history_folder(history_root: Path, date: str, generated_at: datetime) -> Path:
    day = history_root.resolve() / date
    day.mkdir(parents=True, exist_ok=True)
    if not (day / "research.json").exists() and not (day / "script.md").exists():
        return day
    stem = "run-" + generated_at.strftime("%H%M%S")
    for suffix in ("", *(f"-{index:02d}" for index in range(2, 100))):
        candidate = day / (stem + suffix)
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("同一分钟的晨报历史版本过多，请稍后再试")


def run(args: argparse.Namespace) -> int:
    now = datetime.fromisoformat(args.now) if args.now else None
    print(f"[1/4] 搜集过去 {args.hours} 小时的候选信息…", flush=True)
    collected = collect(hours=args.hours, now=now)
    print(f"      找到 {len(collected['candidates'])} 条带明确发布时间的候选。", flush=True)

    print("[2/4] 合并重复事件并按商业价值排序…", flush=True)
    ranked = rank_and_dedupe(collected["candidates"], limit=args.shortlist)
    print(f"      去重后保留 {len(ranked)} 条候选。", flush=True)

    print("[3/4] 打开原始来源并核查证据…", flush=True)
    verified = verify_candidates(ranked)
    verified.sort(key=lambda item: (item["verified"], item["rank_score"]), reverse=True)
    print(f"      {sum(1 for item in verified if item['verified'])}/{len(verified)} 条已打开原页核查。", flush=True)

    print("[4/4] 生成 research.json 和 Scene Flow 口播稿…", flush=True)
    research, script, writer_warnings = write_briefing(
        verified,
        max_stories=args.max_stories,
        settings_path=Path(args.settings) if args.settings else DEFAULT_SETTINGS,
        use_llm=not args.no_llm,
    )
    generated_at = datetime.now().astimezone()
    research.update({
        "window_start": collected["window_start"],
        "window_end": collected["window_end"],
        "generated_at": generated_at.isoformat(),
    })
    warnings = collected["warnings"] + writer_warnings
    if warnings:
        research["warnings"] = warnings

    history = reserve_history_folder(Path(args.history), research["date"], generated_at)
    research["history_path"] = str(history.relative_to(ROOT)).replace("\\", "/")
    research_text = json.dumps(research, ensure_ascii=False, indent=2) + "\n"
    script_text = script.strip() + "\n"
    atomic_text(history / "research.json", research_text)
    atomic_text(history / "script.md", script_text)
    # The board plan is deterministic from research.json. A real script.srt is
    # not available yet, so this first pass uses an estimated timeline; rerun
    # `python -m ai_morning_editor.motion_plan <history-folder>` after the
    # narration is transcribed to snap the boards onto real timestamps.
    plan = write_plan(history, research, script, None)
    output = Path(args.output).resolve()
    atomic_text(output / "research.json", research_text)
    atomic_text(output / "script.md", script_text)
    print(f"完成：{output / 'research.json'}", flush=True)
    print(f"完成：{output / 'script.md'}", flush=True)
    print(f"动效计划：{history / 'motion-plan.json'}（{plan['board_count']} 板）", flush=True)
    print(f"历史：{history}", flush=True)
    if warnings:
        print(f"提示：本次有 {len(warnings)} 条非致命提醒，详情已写入 research.json。", flush=True)
    return 0 if research["stories"] else 2


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="生成过去 24 小时的 AI 商业晨报研究稿和口播稿")
    value.add_argument("--hours", type=int, default=24, choices=range(6, 73), metavar="6-72")
    value.add_argument("--max-stories", type=int, default=5, choices=range(3, 6), metavar="3-5")
    value.add_argument("--shortlist", type=int, default=12, choices=range(5, 21), metavar="5-20")
    value.add_argument("--output", default=str(DEFAULT_OUTPUT))
    value.add_argument("--history", default=str(DEFAULT_HISTORY))
    value.add_argument("--settings", help="可选：兼容 OpenAI 接口的私有设置 JSON")
    value.add_argument("--no-llm", action="store_true", help="不用模型，生成确定性降级稿")
    value.add_argument("--now", help=argparse.SUPPRESS)
    return value


if __name__ == "__main__":
    raise SystemExit(run(parser().parse_args()))
