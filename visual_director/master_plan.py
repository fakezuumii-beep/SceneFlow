"""Visual Master Plan construction and legacy A/B synchronization."""
from __future__ import annotations

import copy
import re
import time
from pathlib import Path

from atomic_files import atomic_json


SCHEMA_VERSION = "sceneflow-visual-master-plan-v1"
# Bumped when the A/B compatibility mapping changes meaning. A stored plan
# keeps the version it was accepted under, so raising this never rewrites an
# episode that has already been reviewed.
LEGACY_ROLE_MAPPING_VERSION = 3
ROLE_TO_LEGACY = {"A": "A", "B": "B", "E": "B", "R": "B", "M": "B", "G": "B"}
OPERATION_PATTERN = re.compile(
    r"(打开|点击|设置|选择|输入|注册|登录|下载|上传|安装|官网|页面|界面|菜单|入口|"
    r"操作|步骤|流程|open\s|click|setting|dashboard|github|website)",
    re.I,
)
NUMBER_PATTERN = re.compile(
    r"(?:\$|¥|￥)?\d+(?:\.\d+)?\s*(?:%|％|倍|秒|分钟|小时|天|周|月|年|万|亿|"
    r"B|M|K|美元|元|个|家|人|次)?",
    re.I,
)
# A figure only implies a data board when it carries a unit or a currency
# mark. A bare year or list index inside a sentence should not promote a shot.
HEADLINE_NUMBER_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|倍|美元|元|万|亿|个|家|名|人|次|条|座席|分钟|小时|天|周|月|年)"
    r"|[$¥￥]\s*\d+"
)
YEAR_REFERENCE_PATTERN = re.compile(r"(?:19|20)\d{2}\s*年")


def has_headline_figure(text):
    """True when the sentence carries a figure worth a data board.

    ``2026 年`` is a time reference in prose, not a headline number, so years
    are skipped instead of promoting the whole shot to motion.
    """
    for match in HEADLINE_NUMBER_PATTERN.finditer(str(text or "")):
        token = match.group(0).strip()
        if YEAR_REFERENCE_PATTERN.fullmatch(token):
            continue
        if not re.search(r"\d", token):
            continue
        return True
    return False


def _importance_number(value):
    if isinstance(value, (int, float)):
        return max(1, min(5, int(value)))
    normalized = str(value or "").strip().lower()
    return {"low": 2, "normal": 3, "high": 5}.get(normalized, 3)


def infer_visual_role(shot, allow_extended_roles=False):
    """Infer a visual role for a shot that does not carry one yet.

    Historically only A and B were reachable, because the legacy storyboard
    could not execute E/R/M/G. Pass ``allow_extended_roles`` when building a
    plan from scratch so a data shot becomes a motion board instead of
    silently collapsing into B-roll. Plans that were already accepted keep the
    old behaviour and are never re-inferred.

    Extended mode stays deliberately conservative: it promotes to M on a real
    data signal and leaves everything else as B-roll, so re-planning does not
    invent new A-roll or evidence work the user never asked for.
    """
    explicit = str(shot.get("visual_role") or "").strip().upper()
    if explicit in ROLE_TO_LEGACY:
        return explicit
    if shot.get("kind") == "A":
        return "A"
    if allow_extended_roles:
        if shot.get("motion_type"):
            return "M"
        if shot.get("recording_required") and shot.get("recording_instruction"):
            return "R"
        if shot.get("generation_concept") or shot.get("generation_prompt"):
            return "G"
        if shot.get("evidence_required") and shot.get("evidence_target"):
            return "E"
        text = str(shot.get("text") or "")
        semantic_type = str(shot.get("semantic_type") or "").lower()
        if semantic_type == "data" or has_headline_figure(text):
            return "M"
    return "B" if shot.get("kind") == "B" else "A"


def _segment_from_shots(shots, index):
    first, last = shots[0], shots[-1]
    role = infer_visual_role(first)
    text = "".join(str(shot.get("text") or "") for shot in shots).strip()
    entity_values = []
    for shot in shots:
        for entity in shot.get("entities") or []:
            if isinstance(entity, dict) and entity.get("name") and entity not in entity_values:
                entity_values.append(copy.deepcopy(entity))
    return {
        "id": str(first.get("visual_segment_id") or f"S{index:03d}"),
        "start": round(float(first["start"]), 3),
        "end": round(float(last["end"]), 3),
        "duration": round(float(last["end"]) - float(first["start"]), 3),
        "text": text,
        "semantic_type": first.get("semantic_type") or "other",
        "visual_role": role,
        "legacy_roll_type": ROLE_TO_LEGACY[role],
        "importance": _importance_number(first.get("importance")),
        "confidence": float(first.get("confidence") or 1),
        "continuity_group": first.get("continuity_group") or f"CG{index:02d}",
        "visual_subject": first.get("visual_subject") or "",
        "entities": entity_values,
        "evidence_required": bool(first.get("evidence_required")),
        "evidence_target": first.get("evidence_target"),
        "evidence_type": first.get("evidence_type"),
        "search_query": first.get("search_query"),
        "stock_search_query": first.get("stock_search_query"),
        "stock_search_query_alt": copy.deepcopy(first.get("stock_search_query_alt") or []),
        "fallback": first.get("fallback"),
        "recording_required": bool(first.get("recording_required")),
        "recording_instruction": first.get("recording_instruction"),
        "motion_type": first.get("motion_type"),
        "motion_data": copy.deepcopy(first.get("motion_data") or {}),
        "generation_concept": first.get("generation_concept"),
        "reason": first.get("reason") or "由旧项目镜头兼容映射",
        "internal_cuts": [],
    }


def from_shots(project, video_profile=None, allow_extended_roles=False):
    """Build a plan from a project's shots.

    ``allow_extended_roles`` is opt-in and only the planning path passes it.
    Structural edits (split/merge) and lazy backfills rebuild with the
    historical A/B mapping so a shot edit can never silently change a role.
    """
    shots = [shot for shot in project.get("shots") or [] if shot.get("start") is not None and shot.get("end") is not None]
    segments = []
    for shot in shots:
        if not shot.get("visual_role"):
            shot["visual_role"] = infer_visual_role(shot, allow_extended_roles=allow_extended_roles)
        shot.setdefault("legacy_roll_type", ROLE_TO_LEGACY[shot["visual_role"]])
        current = segments[-1] if segments else None
        same_segment = bool(
            current
            and current["_shots"]
            and shot.get("visual_segment_id")
            and shot.get("visual_segment_id") == current["id"]
            and infer_visual_role(shot, allow_extended_roles=allow_extended_roles)
            == infer_visual_role(current["_shots"][-1], allow_extended_roles=allow_extended_roles)
        )
        if same_segment:
            current["_shots"].append(shot)
        else:
            segment_id = str(shot.get("visual_segment_id") or f"S{len(segments) + 1:03d}")
            shot["visual_segment_id"] = segment_id
            segments.append({
                "id": segment_id,
                "_shots": [shot],
            })
    output = []
    for index, item in enumerate(segments, 1):
        segment = _segment_from_shots(item["_shots"], index)
        segment["id"] = item["id"]
        output.append(segment)
    return {
        "schema_version": SCHEMA_VERSION,
        "video_type": str(video_profile or project.get("video_profile") or "general"),
        "total_duration": round(float(project.get("duration") or (shots[-1]["end"] if shots else 0)), 3),
        "created_at": time.time(),
        "source": "legacy-project",
        # Record which mapping produced these roles so a reload never re-infers
        # them and a reviewed episode stays exactly as it was accepted.
        "legacy_role_mapping_version": (
            LEGACY_ROLE_MAPPING_VERSION if allow_extended_roles else 2
        ),
        "segments": output,
    }


def build_from_director(candidates, duration, director, video_profile=None):
    by_id = {int(item["id"]): item for item in candidates}
    positions = {int(item["id"]): index for index, item in enumerate(candidates)}
    segments = []
    for index, item in enumerate(director["segments"], 1):
        ids = [int(value) for value in item["candidate_ids"]]
        first_position, last_position = positions[ids[0]], positions[ids[-1]]
        start = 0.0 if first_position == 0 else round(float(candidates[first_position]["start"]), 3)
        end = round(float(duration), 3) if last_position == len(candidates) - 1 else round(float(candidates[last_position + 1]["start"]), 3)
        role = item["visual_role"]
        segment = {
            "id": item["id"],
            "start": start,
            "end": end,
            "duration": round(end - start, 3),
            "text": "".join(str(by_id[value].get("text") or "") for value in ids).strip(),
            "semantic_type": item["semantic_type"],
            "visual_role": role,
            "legacy_roll_type": ROLE_TO_LEGACY[role],
            "importance": item["importance"],
            "confidence": item["confidence"],
            "continuity_group": item["continuity_group"],
            "visual_subject": item["visual_subject"],
            "entities": copy.deepcopy(item["entities"]),
            "evidence_required": bool(item["evidence_required"]),
            "evidence_target": item["evidence_target"],
            "evidence_type": item["evidence_type"],
            "search_query": item["search_query"],
            "stock_search_query": item["stock_search_query"],
            "stock_search_query_alt": copy.deepcopy(item["stock_search_query_alt"]),
            "fallback": item["fallback"],
            "recording_required": bool(item["recording_required"]),
            "recording_instruction": item["recording_instruction"],
            "motion_type": item["motion_type"],
            "motion_data": copy.deepcopy(item["motion_data"] or {}),
            "generation_concept": item["generation_concept"],
            "reason": item["reason"],
            "candidate_ids": ids,
            "internal_cuts": [],
        }
        segments.append(segment)
    return {
        "schema_version": SCHEMA_VERSION,
        "video_type": str(video_profile or director.get("video_type") or "general"),
        "total_duration": round(float(duration), 3),
        "overview": director.get("overview") or "",
        "created_at": time.time(),
        "source": "deepseek",
        "segments": segments,
    }


def finalize(plan, shots):
    output = copy.deepcopy(plan)
    by_segment = {}
    for shot in shots:
        segment_id = shot.get("visual_segment_id")
        if segment_id:
            by_segment.setdefault(segment_id, []).append(shot)
    for segment in output.get("segments", []):
        segment_shots = by_segment.get(segment["id"], [])
        if segment_shots:
            segment["start"] = round(float(segment_shots[0]["start"]), 3)
            segment["end"] = round(float(segment_shots[-1]["end"]), 3)
            segment["duration"] = round(segment["end"] - segment["start"], 3)
            segment["internal_cuts"] = [
                {"start": round(float(shot["start"]), 3), "shot_id": shot["id"]}
                for shot in segment_shots[1:]
            ]
    output["total_duration"] = round(max((float(item["end"]) for item in output.get("segments", [])), default=0), 3)
    return output


def apply_to_shots(plan):
    """Return a segment-to-shot metadata map without touching media assets."""
    output = {}
    for segment in plan.get("segments", []):
        output[segment["id"]] = {
            "visual_segment_id": segment["id"],
            "visual_role": segment["visual_role"],
            "legacy_roll_type": segment.get("legacy_roll_type") or ROLE_TO_LEGACY[segment["visual_role"]],
            "semantic_type": segment.get("semantic_type"),
            "importance": segment.get("importance"),
            "confidence": segment.get("confidence"),
            "continuity_group": segment.get("continuity_group"),
            "visual_subject": segment.get("visual_subject"),
            "entities": copy.deepcopy(segment.get("entities") or []),
            "evidence_required": bool(segment.get("evidence_required")),
            "evidence_target": segment.get("evidence_target"),
            "evidence_type": segment.get("evidence_type"),
            "search_query": segment.get("search_query"),
            "stock_search_query": segment.get("stock_search_query"),
            "stock_search_query_alt": copy.deepcopy(segment.get("stock_search_query_alt") or []),
            "fallback": segment.get("fallback"),
            "recording_required": bool(segment.get("recording_required")),
            "recording_instruction": segment.get("recording_instruction"),
            "motion_type": segment.get("motion_type"),
            "motion_data": copy.deepcopy(segment.get("motion_data") or {}),
            "generation_concept": segment.get("generation_concept"),
        }
    return output


def normalize_project(project):
    changed = False
    if project.get("video_profile") != str(project.get("video_profile") or "general"):
        project["video_profile"] = "general"
        changed = True
    if not project.get("video_profile"):
        project["video_profile"] = "general"
        changed = True
    plan = project.get("visual_master_plan")
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA_VERSION:
        project["visual_master_plan"] = from_shots(project, project.get("video_profile"))
        changed = True
        plan = project["visual_master_plan"]
    if plan.get("source") == "legacy-project":
        mapping_version = plan.get("legacy_role_mapping_version")
        if mapping_version is None or mapping_version < 2:
            # Plans written before the version marker existed carried roles
            # the old renderer could not honour. Collapse them exactly the way
            # v2 always did. Plans that already carry a version are never
            # rewritten, so a reviewed episode reloads byte-for-byte identically.
            for segment in plan.get("segments", []):
                if segment.get("legacy_roll_type") != "A":
                    segment["visual_role"] = "B"
                    segment["legacy_roll_type"] = "B"
                    segment["evidence_required"] = False
                    segment["evidence_target"] = None
                    segment["search_query"] = None
                    segment["recording_required"] = False
                    segment["recording_instruction"] = None
                    segment["motion_type"] = None
                    segment["generation_concept"] = None
            plan["legacy_role_mapping_version"] = 2
            changed = True
    extended_roles = (
        isinstance(plan.get("legacy_role_mapping_version"), int)
        and plan["legacy_role_mapping_version"] >= LEGACY_ROLE_MAPPING_VERSION
    )
    metadata = apply_to_shots(plan)
    for index, shot in enumerate(project.get("shots") or [], 1):
        segment_id = shot.get("visual_segment_id")
        values = metadata.get(segment_id)
        if values:
            for key, value in values.items():
                if shot.get(key) != value:
                    shot[key] = copy.deepcopy(value)
                    changed = True
        role = infer_visual_role(shot, allow_extended_roles=extended_roles)
        if not values:
            fallback = {
                "visual_segment_id": str(shot.get("visual_segment_id") or f"S{index:03d}"),
                "visual_role": role,
                "legacy_roll_type": ROLE_TO_LEGACY[role],
            }
            for key, value in fallback.items():
                if shot.get(key) != value:
                    shot[key] = value
                    changed = True
        if shot.get("kind") != ROLE_TO_LEGACY[role]:
            shot["kind"] = ROLE_TO_LEGACY[role]
            changed = True
        if role == "B" and "generic_stock_allowed" not in shot:
            shot["generic_stock_allowed"] = True
            shot["material_strategy"] = "generic_broll"
            changed = True
    return changed


def set_segment_role(project, segment_id, role):
    role = str(role or "").strip().upper()
    if role not in ROLE_TO_LEGACY:
        raise ValueError("视觉职责只能是 A / B / E / R / M / G")
    plan = project.get("visual_master_plan") or from_shots(project, project.get("video_profile"))
    segment = next((item for item in plan.get("segments", []) if item.get("id") == segment_id), None)
    if not segment:
        raise ValueError("视觉单元不存在")
    changed = segment.get("visual_role") != role
    segment["visual_role"] = role
    segment["legacy_roll_type"] = ROLE_TO_LEGACY[role]
    if role != "B":
        segment["stock_search_query"] = None
        segment["stock_search_query_alt"] = []
    if role != "E":
        segment["evidence_required"] = False
        segment["evidence_target"] = None
        segment["evidence_type"] = None
        segment["search_query"] = None
    if role != "R":
        segment["recording_required"] = False
        segment["recording_instruction"] = None
    if role != "M":
        segment["motion_type"] = None
        segment["motion_data"] = {}
    if role != "G":
        segment["generation_concept"] = None
    if role == "B":
        segment["fallback"] = segment.get("fallback") or "A"
        segment["stock_search_query"] = (
            segment.get("stock_search_query") or segment.get("visual_subject")
        )
    elif role == "R":
        segment["recording_required"] = True
        segment["fallback"] = segment.get("fallback") or "E"
    elif role == "M":
        segment["motion_type"] = segment.get("motion_type") or "M_TITLE"
        segment["motion_data"] = copy.deepcopy(segment.get("motion_data") or {})
        segment["fallback"] = segment.get("fallback") or "A"
    elif role == "G":
        segment["fallback"] = segment.get("fallback") or "A"
    elif role == "E":
        segment["evidence_required"] = True
        segment["evidence_type"] = segment.get("evidence_type") or "official_page"
        segment["fallback"] = segment.get("fallback") or "A"
    project["visual_master_plan"] = plan
    metadata = apply_to_shots(plan)[segment_id]
    for shot in project.get("shots") or []:
        if shot.get("visual_segment_id") != segment_id:
            continue
        if changed and (shot.get("asset") or shot.get("source") or shot.get("candidates")):
            history = shot.setdefault("material_history", [])
            history.append({
                "asset": shot.get("asset"),
                "source": copy.deepcopy(shot.get("source")),
                "role": shot.get("visual_role"),
            })
            for key in ("asset", "source", "candidates", "media_start", "material_status", "material_error"):
                shot.pop(key, None)
            shot["material_status"] = "pending"
        for key, value in metadata.items():
            shot[key] = copy.deepcopy(value)
        shot["kind"] = ROLE_TO_LEGACY[role]
    return changed


def rebuild_after_structural_edit(project):
    """Refresh the plan after a user splits or merges a visual shot."""
    prior = {
        segment.get("id"): segment
        for segment in (project.get("visual_master_plan") or {}).get("segments", [])
    }
    for shot in project.get("shots") or []:
        old = prior.get(shot.get("visual_segment_id"))
        if not old:
            continue
        shot.setdefault("visual_role", old.get("visual_role"))
        shot.setdefault("semantic_type", old.get("semantic_type"))
        shot.setdefault("importance", old.get("importance"))
        shot.setdefault("motion_type", old.get("motion_type"))
        shot.setdefault("motion_data", copy.deepcopy(old.get("motion_data") or {}))
        shot.setdefault("evidence_target", old.get("evidence_target"))
        shot.setdefault("evidence_type", old.get("evidence_type"))
        shot.setdefault("stock_search_query", old.get("stock_search_query"))
        shot.setdefault("stock_search_query_alt", copy.deepcopy(old.get("stock_search_query_alt") or []))
        shot.setdefault("recording_instruction", old.get("recording_instruction"))
        shot.setdefault("generation_concept", old.get("generation_concept"))
    rebuilt = from_shots(project, project.get("video_profile"))
    project["visual_master_plan"] = finalize(rebuilt, project.get("shots") or [])
    return project["visual_master_plan"]


def to_markdown(plan):
    lines = [
        '# Visual Master Plan',
        '',
        f"- video_type: {plan.get('video_type') or 'general'}",
        f"- total_duration: {plan.get('total_duration') or 0:.3f}s",
        f"- schema_version: {plan.get('schema_version')}",
        '',
        '| ID | 时间 | 角色 | 原文 | 内部切点 | Motion | 连续性 | 状态 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |',
    ]
    for segment in plan.get('segments', []):
        cuts = ', '.join(f"{item.get('start')}s" for item in segment.get('internal_cuts') or []) or '-'
        text = str(segment.get('text') or '').replace('|', '｜').replace('\n', ' ')[:120]
        lines.append(
            f"| {segment.get('id')} | {segment.get('start')}–{segment.get('end')} | "
            f"{segment.get('visual_role')} | {text} | {cuts} | "
            f"{segment.get('motion_type') or '-'} | {segment.get('continuity_group') or '-'} | "
            f"{segment.get('execution',{}).get('material_strategy') or '-'} |"
        )
    return '\n'.join(lines).rstrip() + '\n'


def motion_queue_markdown(plan):
    lines = [
        '# Motion Production Queue',
        '',
        '| FX | 总表回链 | 时间 | 模板 | 传播作用 | 状态 |',
        '| --- | --- | --- | --- | --- | --- |',
    ]
    index = 0
    for segment in plan.get('segments', []):
        if segment.get('visual_role') != 'M':
            continue
        index += 1
        text = str(segment.get('text') or '').replace('|', '｜').replace('\n', ' ')[:100]
        lines.append(
            f"| FX{index:02d} | {segment.get('id')} | {segment.get('start')}–{segment.get('end')} | "
            f"{segment.get('motion_type') or 'M_TITLE'} | {text} | planned |"
        )
    if index == 0:
        lines.append('| - | - | - | - | 当前总表没有 M 类动效 | - |')
    return '\n'.join(lines).rstrip() + '\n'


def write_plan(project, folder=None):
    plan = project.get("visual_master_plan")
    if not isinstance(plan, dict):
        return None
    raw_folder = folder or project.get("_folder") or ""
    if not raw_folder:
        return None
    folder = Path(raw_folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "visual-master-plan.json"
    atomic_json(target, plan)
    (folder / "visual-master-plan.md").write_text(to_markdown(plan), encoding="utf-8")
    (folder / "motion-production-queue.md").write_text(motion_queue_markdown(plan), encoding="utf-8")
    return target
