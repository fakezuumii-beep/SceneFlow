"""Deterministic Motion Director for Remotion-compatible shot props."""
from __future__ import annotations

import re


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
# scene_flow keeps the original static-still templates; intel_board is the
# animated 情报板式 renderer in motion/intel_board.py.
MOTION_STYLES = ("scene_flow", "intel_board")
DEFAULT_MOTION_STYLE = "scene_flow"
NUMBER_RE = re.compile(
    r"(?:\$|¥|￥)?\d+(?:\.\d+)?\s*(?:%|％|倍|秒|分钟|小时|天|周|月|年|万|亿|B|M|K|美元|元|个|家|人|次)?",
    re.I,
)


def _clean_items(text):
    values = re.split(r"\s*(?:、|，|,|；|;|以及|和|\bvs\.?\b|对比)\s*", str(text or ""), flags=re.I)
    output = []
    for value in values:
        item = re.sub(r"[。！？!?]+$", "", value).strip()
        if item and item not in output:
            output.append(item[:40])
    return output[:5]


def _numbers(text):
    values = []
    for value in NUMBER_RE.findall(str(text or "")):
        value = value.strip()
        if value and value not in values:
            values.append(value)
    return values[:5]


def normalize_motion_style(value):
    requested = str(value or "").strip().lower()
    return requested if requested in MOTION_STYLES else DEFAULT_MOTION_STYLE


def normalize_motion_type(value, text=""):
    requested = str(value or "").strip().upper()
    if requested in MOTION_TYPES:
        return requested
    content = str(text or "")
    numbers = _numbers(content)
    items = _clean_items(content)
    if len(numbers) >= 2:
        return "M_COMPARE"
    if numbers:
        return "M_NUMBER"
    if "→" in content or "->" in content:
        return "M_PROCESS"
    if len(re.findall(r"(?:19|20)\d{2}", content)) >= 2:
        return "M_TIMELINE"
    if len(items) >= 4:
        return "M_LIST"
    if re.search(r"第[一二三四五六七八九十\d]+|排名|排行", content):
        return "M_RANKING"
    return "M_TITLE"


def build_motion_plan(segment, duration, aspect_ratio="16:9", style=DEFAULT_MOTION_STYLE):
    motion_type = normalize_motion_type(segment.get("motion_type"), segment.get("text", ""))
    motion_style = normalize_motion_style(style)
    text = str(segment.get("text") or "").strip()
    title = str(segment.get("visual_subject") or text[:20] or "重点信息").strip()
    items = _clean_items(text)
    numbers = _numbers(text)
    images = [
        str(entity.get("name"))
        for entity in (segment.get("entities") or [])
        if isinstance(entity, dict) and entity.get("name")
    ][:6]
    highlight_index = 0
    if motion_type == "M_RANKING" and numbers:
        highlight_index = max(range(len(numbers)), key=lambda index: float(re.sub(r"[^\d.]", "", numbers[index]) or 0))
    props = {
        "duration": round(max(float(duration or 0), .1), 3),
        "title": title[:80],
        "items": items,
        "images": images,
        "numbers": numbers,
        "highlight_index": highlight_index,
        "aspect_ratio": aspect_ratio if aspect_ratio in ("9:16", "1:1", "16:9") else "16:9",
    }
    for key, value in (segment.get("motion_data") or {}).items():
        props[key] = value
    return {
        "template": motion_type,
        "style": motion_style,
        "composition_id": (
            f"sceneflow-{motion_style}-{motion_type.lower()}-{aspect_ratio.replace(':','x')}"
        ),
        "props": props,
    }


class MotionResolver:
    def resolve(self, project, shot, output_size, options=None):
        import core as c
        from .renderer import motion_cache_key, render_motion_clip

        folder = c.project_dir(project['id'])
        cache = folder / 'cache' / 'motion'
        cache.mkdir(parents=True, exist_ok=True)
        key = motion_cache_key(shot, output_size)
        clip = cache / f'{key}.mp4'
        preview = cache / f'{key}.png'
        if not clip.is_file():
            render_motion_clip(shot, output_size, clip)
        if not preview.is_file():
            still = clip.with_suffix('.png')
            if still.is_file():
                preview.write_bytes(still.read_bytes())
        assets = folder / 'assets'
        final_clip = assets / f'motion-{key}.mp4'
        final_preview = assets / f'motion-{key}.png'
        if not final_clip.exists():
            import shutil
            shutil.copy2(clip, final_clip)
        if preview.is_file() and not final_preview.exists():
            import shutil
            shutil.copy2(preview, final_preview)
        return {
            'asset_type': 'video',
            'asset_path': final_clip.relative_to(folder).as_posix(),
            'preview_path': final_preview.relative_to(folder).as_posix() if final_preview.exists() else None,
            'duration': round(max(.1, float(shot['end']) - float(shot['start'])), 3),
            'source': shot.get('motion_type') or 'M_TITLE',
            'metadata': {
                'resolver': 'motion',
                'template': shot.get('motion_type') or 'M_TITLE',
                'motion_style': normalize_motion_style(shot.get('motion_style')),
                'motion_data': shot.get('motion_data') or {},
                'motion_plan': shot.get('motion_plan') or {},
            },
            'status': 'ready',
        }
