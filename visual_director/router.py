"""Route visual responsibilities to deterministic execution paths."""
from __future__ import annotations

import copy

from motion.template_router import (
    build_motion_plan,
    normalize_motion_style,
    normalize_motion_type,
)

from .master_plan import ROLE_TO_LEGACY
from .stock_resolver import resolve_stock_queries


def _route(segment, options=None):
    role = str(segment.get("visual_role") or "A").upper()
    aspect_ratio = str((options or {}).get("aspect_ratio") or "16:9")
    route = {
        "visual_role": role,
        "legacy_roll_type": ROLE_TO_LEGACY[role],
        "processor": {
            "A": "aroll",
            "B": "stock",
            "E": "evidence",
            "R": "evidence",
            "M": "motion",
            "G": "generation",
        }[role],
        "material_strategy": "aroll",
        "generic_stock_allowed": False,
        "fallback_role": segment.get("fallback") or "A",
    }
    if role == "B":
        route.update(
            material_strategy="generic_broll",
            generic_stock_allowed=True,
            stock_queries=resolve_stock_queries(segment),
        )
    elif role == "E":
        route.update(
            material_strategy="official_evidence",
            evidence_priority=["official_evidence", "web_evidence", "existing_assets", segment.get("fallback") or "A"],
            evidence_target=segment.get("evidence_target"),
            evidence_type=segment.get("evidence_type"),
            search_query=segment.get("search_query"),
        )
    elif role == "R":
        route.update(
            material_strategy="evidence_fallback",
            recording_required=True,
            recording_instruction=segment.get("recording_instruction"),
            execution_as="E",
            fallback_role=segment.get("fallback") or "E",
        )
    elif role == "M":
        motion_type = normalize_motion_type(segment.get("motion_type"), segment.get("text", ""))
        motion_style = normalize_motion_style((options or {}).get("motion_style"))
        route.update(
            material_strategy="motion_template",
            motion_type=motion_type,
            motion_style=motion_style,
            motion_data=copy.deepcopy(segment.get("motion_data") or {}),
            motion_plan=build_motion_plan(
                segment, segment.get("duration", 0), aspect_ratio, motion_style
            ),
            fallback_role="A",
        )
    elif role == "G":
        route.update(
            material_strategy="generated_shot",
            generic_stock_allowed=False,
            generation_concept=segment.get("generation_concept"),
            fallback_role="A",
        )
    return route


def _share_board_clock(project):
    """Give every part of one motion board its slice of a single build clock.

    A long data segment is split into several M shots and each part renders its
    own clip. Without an offset every part replays the board from an empty
    frame, so a comparison would build itself once per cut instead of once.
    """
    groups = {}
    for shot in project.get("shots") or []:
        if str(shot.get("visual_role") or "").upper() != "M":
            continue
        groups.setdefault(shot.get("visual_segment_id"), []).append(shot)
    for shots in groups.values():
        try:
            origin = min(float(shot.get("start") or 0) for shot in shots)
            span = max(float(shot.get("end") or 0) for shot in shots) - origin
        except (TypeError, ValueError):
            continue
        for shot in shots:
            plan = shot.get("motion_plan")
            if not isinstance(plan, dict) or not isinstance(plan.get("props"), dict):
                continue
            props = plan["props"]
            try:
                props["build_offset"] = round(max(0.0, float(shot.get("start") or 0) - origin), 3)
            except (TypeError, ValueError):
                props["build_offset"] = 0.0
            if span > 0:
                try:
                    props["duration"] = round(max(span, float(props.get("duration") or 0)), 3)
                except (TypeError, ValueError):
                    props["duration"] = round(span, 3)


def apply_routes(project):
    plan = project.get("visual_master_plan") or {}
    routes = {}
    for segment in plan.get("segments", []):
        route = _route(segment, project.get("options") or {})
        segment["execution"] = copy.deepcopy(route)
        routes[segment["id"]] = route
    for shot in project.get("shots") or []:
        route = routes.get(shot.get("visual_segment_id"))
        if not route:
            continue
        for key, value in route.items():
            shot[key] = copy.deepcopy(value)
    _share_board_clock(project)
    return routes


def refresh_shot_route(project, shot):
    segment_id = shot.get("visual_segment_id")
    segment = next(
        (item for item in (project.get("visual_master_plan") or {}).get("segments", [])
         if item.get("id") == segment_id),
        None,
    )
    if not segment:
        return None
    route = _route(segment, project.get("options") or {})
    shot.update(copy.deepcopy(route))
    return route
