"""Unified dispatch from visual role to the owning asset resolver."""
from __future__ import annotations

from motion.template_router import MotionResolver

from .evidence import EvidenceResolver
from .timeline import apply_asset_result, sync_visual_timeline


class VisualAssetResolver:
    def __init__(self, settings, stock_resolver=None):
        self.settings = settings
        self.stock_resolver = stock_resolver
        self.evidence = EvidenceResolver()
        self.motion = MotionResolver()

    def resolve(self, project, shot, output_size):
        role = str(shot.get('visual_role') or ('A' if shot.get('kind') == 'A' else 'B')).upper()
        if role == 'A':
            return {'asset_type': 'video', 'asset_path': shot.get('aroll_asset'), 'status': 'ready' if shot.get('aroll_asset') else 'pending'}
        if role == 'B':
            if not self.stock_resolver:
                raise RuntimeError('普通素材 Resolver 尚未连接')
            result = self.stock_resolver(project, shot)
        elif role in ('E', 'R'):
            result = self.evidence.resolve(project, shot, output_size, project.get('options'))
        elif role == 'M':
            result = self.motion.resolve(project, shot, output_size, project.get('options'))
        elif role == 'G':
            from providers.generation import generate_scene
            result = generate_scene(self.settings, project, shot)
        else:
            raise ValueError(f'不支持的视觉职责：{role}')
        apply_asset_result(shot, result)
        sync_visual_timeline(project)
        return result
