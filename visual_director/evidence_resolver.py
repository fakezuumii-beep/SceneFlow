"""Resolve evidence, recording, motion, and fallback material strategies."""
from __future__ import annotations


def resolve(project, shot):
    """Return the deterministic material decision for one visual shot.

    This first implementation never converts a named news entity into a
    generic stock query. Official evidence and web evidence remain unresolved
    until an asset is imported or a later resolver supplies one.
    """
    role = str(shot.get("visual_role") or "").upper()
    if not role and shot.get("kind") == "B":
        return {"status": "pending", "strategy": "legacy_broll", "fallback": None}
    if not role:
        role = "A"
    if role == "A":
        return {"status": "host", "strategy": "aroll", "fallback": None}
    if shot.get("asset"):
        return {
            "status": "ready",
            "strategy": str(shot.get("material_strategy") or "existing_assets"),
            "fallback": None,
        }
    if role == "B":
        return {"status": "pending", "strategy": "generic_broll", "fallback": None}
    if role == "E":
        return {
            "status": "missing",
            "strategy": "official_evidence",
            "fallback": shot.get("fallback") or "A",
            "reason": "已找到真实证据主体，等待官方页面、截图、网页或现有真实素材，不使用泛素材替代",
            "target": shot.get("evidence_target"),
            "query": shot.get("search_query"),
        }
    if role == "R":
        return {
            "status": "missing",
            "strategy": "recording",
            "fallback": shot.get("fallback") or "E",
            "reason": "需要录屏或手动上传操作画面",
            "target": shot.get("recording_instruction"),
        }
    if role == "M":
        return {"status": "motion", "strategy": "motion_template", "fallback": None}
    if role == "G":
        return {
            "status": "missing",
            "strategy": "generated_shot",
            "fallback": shot.get("fallback") or "A",
            "reason": "需要 AI 生成镜头；第一阶段先保留生成位并回退人物画面",
            "concept": shot.get("generation_concept"),
        }
    return {"status": "pending", "strategy": "legacy_broll", "fallback": None}


def can_use_generic_stock(shot):
    return bool(shot.get("generic_stock_allowed") and shot.get("visual_role") == "B")
