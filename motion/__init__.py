"""Motion template routing for SceneFlow."""

from .template_router import (
    DEFAULT_MOTION_STYLE,
    MOTION_STYLES,
    build_motion_plan,
    normalize_motion_style,
    normalize_motion_type,
)

__all__ = [
    "DEFAULT_MOTION_STYLE",
    "MOTION_STYLES",
    "build_motion_plan",
    "normalize_motion_style",
    "normalize_motion_type",
]
