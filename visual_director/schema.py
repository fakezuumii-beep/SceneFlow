"""Strict schema validation for Visual Director responses."""
from __future__ import annotations

import copy
import re


ROLES = ("A", "B", "E", "R", "M", "G")
MOTION_TYPES = (
    "M_TITLE",
    "M_COMPARE",
    "M_LIST",
    "M_TIMELINE",
    "M_NUMBER",
    "M_RANKING",
    "M_PROCESS",
    "M_GALLERY",
)
ENTITY_TYPES = (
    "company",
    "product",
    "person",
    "model",
    "organization",
    "website",
    "document",
    "data",
    "event",
    "other",
)
FORBIDDEN_FIELDS = {
    "start",
    "end",
    "duration",
    "kind",
    "roll_type",
    "a_roll",
    "b_roll",
    "aroll",
    "broll",
    "shot_count",
    "shots",
    "visual_shots",
    "from",
    "to",
    "transition",
    "camera",
}
SEGMENT_FIELDS = {
    "segment_id",
    "candidate_ids",
    "text",
    "semantic_type",
    "visual_role",
    "confidence",
    "entities",
    "visual_subject",
    "evidence_required",
    "evidence_target",
    "evidence_type",
    "search_query",
    "stock_search_query",
    "stock_search_query_alt",
    "fallback",
    "recording_required",
    "recording_instruction",
    "motion_type",
    "motion_data",
    "generation_concept",
    "importance",
    "continuity_group",
    "reason",
}


def _normalized_text(value):
    return re.sub(r"\s+", "", str(value or "")).strip()


def _number(value, default, label, minimum=None, maximum=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        if default is not None:
            result = float(default)
        else:
            raise ValueError(f"{label}无效") from None
    if minimum is not None and result < minimum:
        raise ValueError(f"{label}小于允许范围")
    if maximum is not None and result > maximum:
        raise ValueError(f"{label}超出允许范围")
    return result


def _ordered_candidate_ids(raw, candidates):
    values = raw.get("candidate_ids")
    if not isinstance(values, list) or not values:
        raise ValueError("视觉单元必须提供连续 candidate_ids")
    output = []
    for value in values:
        if isinstance(value, bool):
            raise ValueError("candidate_ids 必须是整数")
        try:
            item = int(value)
        except (TypeError, ValueError):
            raise ValueError("candidate_ids 必须是整数") from None
        if item not in candidates:
            raise ValueError("视觉单元引用了不存在的原文片段")
        if item in output:
            raise ValueError("candidate_ids 不能重复")
        output.append(item)
    return output


def _entities(raw):
    values = raw.get("entities") or []
    if not isinstance(values, list):
        raise ValueError("entities 必须是数组")
    output = []
    for value in values[:20]:
        if not isinstance(value, dict):
            raise ValueError("entities 每一项必须是对象")
        name = str(value.get("name") or "").strip()[:120]
        entity_type = str(value.get("type") or "other").strip().lower()
        if not name:
            continue
        if entity_type not in ENTITY_TYPES:
            entity_type = "other"
        output.append({"name": name, "type": entity_type})
    return output


def validate_director_response(payload, candidates, rules):
    """Validate one full-script Visual Director JSON object.

    The model owns semantic understanding only. Timing, final durations, cuts,
    transitions, material strategy, and render parameters are intentionally
    rejected if the model tries to return them.
    """
    if not isinstance(payload, dict):
        raise ValueError("视觉导演必须返回 JSON 对象")
    if set(payload) - {"video_type", "overview", "segments"}:
        raise ValueError("视觉导演返回了未允许的顶层字段")
    items = payload.get("segments")
    if not isinstance(items, list) or not items:
        raise ValueError("视觉导演必须返回非空 segments")

    candidate_by_id = {int(item["id"]): item for item in candidates}
    candidate_positions = {int(item["id"]): index for index, item in enumerate(candidates)}
    allowed_semantic = set(rules["semantic_types"])
    expected_position = 0
    seen_segment_ids = set()
    output = []
    for raw in items:
        if not isinstance(raw, dict):
            raise ValueError("视觉导演 segments 每一项必须是对象")
        if set(raw) - SEGMENT_FIELDS:
            raise ValueError("视觉导演返回了未允许的视觉单元字段")
        forbidden = FORBIDDEN_FIELDS.intersection(raw)
        if forbidden:
            raise ValueError("视觉导演返回了程序负责的剪辑字段：" + "、".join(sorted(forbidden)))

        candidate_ids = _ordered_candidate_ids(raw, candidate_by_id)
        positions = [candidate_positions[item] for item in candidate_ids]
        if positions != list(range(expected_position, expected_position + len(positions))):
            raise ValueError("视觉单元必须按原文顺序连续覆盖，不能重复、跳段或重叠")
        expected_position += len(positions)

        text = "".join(str(candidate_by_id[item].get("text") or "") for item in candidate_ids).strip()
        if raw.get("text") and _normalized_text(raw["text"]) != _normalized_text(text):
            raise ValueError("视觉导演不能修改原文")

        segment_id = str(raw.get("segment_id") or f"S{len(output) + 1:03d}").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", segment_id):
            raise ValueError("segment_id 格式无效")
        if segment_id in seen_segment_ids:
            raise ValueError("segment_id 不能重复")
        seen_segment_ids.add(segment_id)

        semantic_type = str(raw.get("semantic_type") or "").strip().lower()
        if semantic_type not in allowed_semantic:
            raise ValueError("视觉导演返回了未配置的 semantic_type")
        visual_role = str(raw.get("visual_role") or "").strip().upper()
        if visual_role not in ROLES:
            raise ValueError("visual_role 只能是 A / B / E / R / M / G")

        confidence = _number(raw.get("confidence"), 0.8, "confidence", 0, 1)
        try:
            importance = int(raw.get("importance", 3))
        except (TypeError, ValueError):
            raise ValueError("importance 必须是 1 到 5 的整数") from None
        if not 1 <= importance <= 5:
            raise ValueError("importance 必须是 1 到 5 的整数")

        visual_subject = re.sub(r"\s+", " ", str(raw.get("visual_subject") or "")).strip()[:160]
        evidence_required = bool(raw.get("evidence_required", visual_role == "E"))
        evidence_target = str(raw.get("evidence_target") or "").strip()[:240]
        evidence_type = str(raw.get("evidence_type") or "").strip()[:80] or None
        search_query = str(raw.get("search_query") or "").strip()[:240]
        stock_search_query = str(raw.get("stock_search_query") or "").strip()[:240]
        raw_alt = raw.get("stock_search_query_alt") or []
        if not isinstance(raw_alt, list):
            raise ValueError("stock_search_query_alt 必须是数组")
        stock_search_query_alt = []
        for value in raw_alt[:3]:
            query = str(value or "").strip()[:240]
            if query and query not in stock_search_query_alt:
                stock_search_query_alt.append(query)
        fallback = str(raw.get("fallback") or "").strip().upper()
        if fallback and fallback not in ROLES:
            raise ValueError("fallback 只能是 A / B / E / R / M / G")

        recording_required = bool(raw.get("recording_required", visual_role == "R"))
        recording_instruction = str(raw.get("recording_instruction") or "").strip()[:500]
        motion_type = str(raw.get("motion_type") or "").strip().upper() or None
        motion_data = raw.get("motion_data")
        if motion_data is not None and not isinstance(motion_data, dict):
            raise ValueError("motion_data 必须是对象")
        motion_data = motion_data or {}
        generation_concept = str(raw.get("generation_concept") or "").strip()[:500]

        if visual_role == "E":
            if not evidence_required:
                raise ValueError("E 类必须是真实证据，evidence_required 必须为 true；普通场景应使用 B")
            if not evidence_target or not search_query:
                raise ValueError("E 类真实证据必须提供 evidence_target 和 search_query")
        elif visual_role == "B":
            if not (stock_search_query or search_query or visual_subject):
                raise ValueError("B 类普通素材必须提供 stock_search_query 或 visual_subject")
            if any((evidence_target, motion_type, generation_concept)):
                raise ValueError("B 类不应同时填写 E/M/G 字段")
        elif visual_role == "R":
            if not recording_required:
                raise ValueError("R 类录屏必须标记 recording_required=true")
            if not recording_instruction:
                raise ValueError("R 类录屏必须提供 recording_instruction")
        elif visual_role == "M":
            if motion_type not in MOTION_TYPES:
                raise ValueError("M 类动效必须返回支持的 motion_type")
            if not motion_data:
                raise ValueError("M 类动效必须返回结构化 motion_data")
            if any((stock_search_query, evidence_target, generation_concept)):
                raise ValueError("M 类不应同时填写 B/E/G 字段")
        elif visual_role == "G":
            if not generation_concept:
                raise ValueError("G 类生成镜头必须提供 generation_concept")
            if any((stock_search_query, evidence_target, motion_type)):
                raise ValueError("G 类不应同时填写 B/E/M 字段")

        continuity_group = str(raw.get("continuity_group") or f"CG{len(output) + 1:02d}").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", continuity_group):
            raise ValueError("continuity_group 格式无效")

        output.append({
            "id": segment_id,
            "candidate_ids": candidate_ids,
            "text": text,
            "semantic_type": semantic_type,
            "visual_role": visual_role,
            "confidence": round(confidence, 3),
            "entities": _entities(raw),
            "visual_subject": visual_subject,
            "evidence_required": evidence_required,
            "evidence_target": evidence_target or None,
            "evidence_type": evidence_type,
            "search_query": search_query or visual_subject or None,
            "stock_search_query": stock_search_query or None,
            "stock_search_query_alt": stock_search_query_alt,
            "fallback": fallback or {"A":"A","B":"A","E":"A","R":"E","M":"A","G":"A"}[visual_role],
            "recording_required": recording_required,
            "recording_instruction": recording_instruction or None,
            "motion_type": motion_type,
            "motion_data": copy.deepcopy(motion_data) if motion_data else None,
            "generation_concept": generation_concept or None,
            "importance": importance,
            "continuity_group": continuity_group,
            "reason": str(raw.get("reason") or "").strip()[:600],
        })

    if expected_position != len(candidates):
        raise ValueError("视觉导演没有完整覆盖整篇文案")
    return {
        "video_type": str(payload.get("video_type") or "general")[:80],
        "overview": str(payload.get("overview") or "")[:1000],
        "segments": output,
    }
