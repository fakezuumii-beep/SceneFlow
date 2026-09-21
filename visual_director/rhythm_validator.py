"""Whole-film visual pacing validation."""
from __future__ import annotations

from collections import Counter


ROLES = ("A", "B", "E", "R", "M", "G")


def _timeline(segments):
    """Order the plan by start time and drop units nested inside a longer one.

    A short phrase merged into a continuous A-roll run stays in the plan as a
    child of its parent segment, so the raw list holds both the merged unit and
    its children. Summing them double-counted the merged seconds and reported
    more visual time than the episode is long.
    """
    ordered = []
    for segment in segments:
        try:
            start = float(segment.get("start") or 0)
            end = float(segment.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if end > start:
            ordered.append((start, end, segment))
    ordered.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    kept = []
    for start, end, segment in ordered:
        nested = any(
            other_start <= start + 1e-6 and other_end >= end - 1e-6
            and (other_end - other_start) > (end - start) + 1e-6
            for other_start, other_end, _ in kept
        )
        if not nested:
            kept.append((start, end, segment))
    return kept


def _run_lengths(timeline):
    """Group consecutive same-role units and measure each run by its real span.

    Durations come from the span, never from a sum, so a partially overlapping
    neighbour cannot inflate a run.
    """
    runs = []
    current = None
    for start, end, segment in timeline:
        role = segment.get("visual_role")
        if current and current["role"] == role:
            current["start"] = min(current["start"], start)
            current["end"] = max(current["end"], end)
            current["ids"].append(segment.get("id"))
        else:
            if current:
                runs.append(current)
            current = {"role": role, "start": start, "end": end, "ids": [segment.get("id")]}
    if current:
        runs.append(current)
    for run in runs:
        run["duration"] = max(0.0, run["end"] - run["start"])
    return runs


def _role_totals(timeline, runs, shots):
    """Per-role unit counts and seconds, taken from the shots when available.

    The shots are the rendered timeline, so they are the only authority on how
    much A-roll or evidence time the episode actually carries. Without them the
    runs still give a span-accurate duration for every role.
    """
    if shots:
        counts = Counter(shot.get("visual_role") for shot in shots)
        seconds = {
            role: round(sum(
                max(0.0, float(shot.get("end") or 0) - float(shot.get("start") or 0))
                for shot in shots if shot.get("visual_role") == role
            ), 3)
            for role in ROLES
        }
        return {role: counts.get(role, 0) for role in ROLES}, seconds
    counts = Counter(segment.get("visual_role") for _, _, segment in timeline)
    seconds = {
        role: round(sum(run["duration"] for run in runs if run["role"] == role), 3)
        for role in ROLES
    }
    return {role: counts.get(role, 0) for role in ROLES}, seconds


def validate(plan, shots=None):
    segments = list(plan.get("segments") or [])
    timeline = _timeline(segments)
    warnings = []
    runs = _run_lengths(timeline)
    for run in runs:
        if run["role"] == "A" and run["duration"] > 15.0:
            warnings.append({
                "code": "continuous_aroll",
                "severity": "warning",
                "segment_ids": run["ids"],
                "message": f"连续 A 类视觉 {run['duration']:.1f} 秒，建议检查其中是否包含证据或动效单元",
            })
        if run["role"] in ("B", "E") and run["duration"] > 20.0:
            kind = "说明性素材" if run["role"] == "B" else "证据画面"
            warnings.append({
                "code": "continuous_detail",
                "severity": "warning",
                "segment_ids": run["ids"],
                "message": f"连续{kind} {run['duration']:.1f} 秒，建议在自然观点节点回主播换气",
            })
        if run["role"] in ("M", "G") and run["duration"] > 12.0:
            warnings.append({
                "code": "high_intensity_run",
                "severity": "warning",
                "segment_ids": run["ids"],
                "message": f"高强度 {run['role']} 画面连续 {run['duration']:.1f} 秒，建议插入稳定或证据画面",
            })

    total = sum(end - start for start, end, _ in timeline)
    generated = sum(
        end - start for start, end, segment in timeline
        if segment.get("visual_role") == "G"
    )
    if total > 0 and generated / total > 0.30:
        warnings.append({
            "code": "generated_ratio",
            "severity": "warning",
            "segment_ids": [segment.get("id") for _, _, segment in timeline
                            if segment.get("visual_role") == "G"],
            "message": f"AI 生成镜头占比 {generated / total:.0%}，超过建议上限 30%",
        })

    signatures = []
    for _, _, segment in timeline:
        signature = (
            str(segment.get("visual_role") or ""),
            str(segment.get("visual_subject") or "").strip().lower(),
            str(segment.get("search_query") or "").strip().lower(),
        )
        if signature[1] or signature[2]:
            signatures.append((segment.get("id"), signature))
    for index in range(1, len(signatures)):
        if signatures[index - 1][1] == signatures[index][1]:
            if not any(item["code"] == "adjacent_duplicate" for item in warnings):
                warnings.append({
                    "code": "adjacent_duplicate",
                    "severity": "warning",
                    "segment_ids": [signatures[index - 1][0], signatures[index][0]],
                    "message": "相邻视觉单元的主体或搜索意图重复，建议合并或更换其中一个",
                })
    role_counts, role_duration = _role_totals(timeline, runs, shots)
    return {
        "ok": not warnings,
        "warnings": warnings,
        "role_counts": role_counts,
        "role_duration": role_duration,
    }
