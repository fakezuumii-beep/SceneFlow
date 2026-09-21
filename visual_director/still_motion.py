"""Stable still-image motion policies.

FFmpeg zoompan performs integer crop movement and can visibly jitter on slow
pushes, especially after vertical crop/scale. SceneFlow deliberately uses a
static hold plus a short fade for generated stills instead.
"""
from __future__ import annotations


def stable_still_filter(width, height, fps=30, fade=0.18):
    fade = max(0.0, min(0.35, float(fade)))
    chain = (
        f'scale={int(width)}:{int(height)}:force_original_aspect_ratio=increase,'
        f'crop={int(width)}:{int(height)},setsar=1,fps={int(fps)}'
    )
    if fade > 0:
        chain += f',fade=t=in:st=0:d={fade:.3f}'
    return chain
