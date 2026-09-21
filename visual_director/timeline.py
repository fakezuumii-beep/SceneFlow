"""Unified Timeline Clip schema shared by all visual roles."""
from __future__ import annotations

import copy
import hashlib


SCHEMA_VERSION = 'sceneflow-visual-timeline-v1'


def _asset_type(path):
    suffix = str(path or '').lower().rsplit('.', 1)[-1]
    if suffix in ('mp4', 'mov', 'mkv', 'webm', 'm4v'):
        return 'video'
    if suffix in ('png', 'jpg', 'jpeg', 'webp'):
        return 'image'
    return 'remotion' if path == 'remotion' else 'none'


def apply_asset_result(shot, result):
    if not isinstance(result, dict) or result.get('status') not in ('ready', 'motion'):
        return shot
    path = result.get('asset_path')
    if path:
        shot['asset'] = path
        shot['asset_type'] = result.get('asset_type') or _asset_type(path)
    if result.get('preview_path'):
        shot['preview_asset'] = result['preview_path']
    shot['material_status'] = 'ready'
    shot['material_error'] = None
    shot['resolver_metadata'] = copy.deepcopy(result.get('metadata') or {})
    shot['resolver_source'] = result.get('source')
    if isinstance(result.get('source'),dict):
        shot['source']=copy.deepcopy(result['source'])
    elif result.get('source'):
        resolved=str(result['source'])
        page=resolved if resolved.startswith(('http://','https://')) else ''
        existing=shot.get('source') or {}
        # A fresh resolver capture replaces an earlier generated page so the
        # manifest keeps pointing at the screenshot that is really on screen;
        # a source the operator chose by hand is left untouched.
        if not existing or (existing.get('provider')=='evidence' and existing.get('page')!=page):
            shot['source']={
                'provider':str((result.get('metadata') or {}).get('provider') or (result.get('metadata') or {}).get('resolver') or 'resolver'),
                'page':page,
                'name':resolved,
            }
    return shot


def _clip(project, shot, index):
    if shot.get('start') is None or shot.get('end') is None:
        return None
    role = str(shot.get('visual_role') or ('A' if shot.get('kind') == 'A' else 'B')).upper()
    if role == 'A':
        path = shot.get('aroll_asset')
        source = copy.deepcopy(shot.get('aroll_provenance') or {})
        status = 'ready' if path else 'pending'
    else:
        path = shot.get('asset')
        source = {
            'resolver': shot.get('material_strategy'),
            'provider': (shot.get('source') or {}).get('provider'),
            'metadata': copy.deepcopy(shot.get('resolver_metadata') or {}),
            'page': (shot.get('source') or {}).get('page'),
        }
        status = str(shot.get('material_status') or ('ready' if path else 'pending'))
    clip_id = shot.get('clip_id') or 'C' + hashlib.sha256(
        f'{project.get("id")}:{shot.get("id")}:{index}'.encode()
    ).hexdigest()[:10].upper()
    return {
        'clip_id': clip_id,
        'segment_id': shot.get('visual_segment_id'),
        'shot_id': shot.get('id'),
        'visual_role': role,
        'legacy_roll_type': shot.get('legacy_roll_type') or ('A' if role == 'A' else 'B'),
        'start': round(float(shot['start']), 3),
        'duration': round(float(shot['end']) - float(shot['start']), 3),
        'asset': {
            'type': shot.get('asset_type') or _asset_type(path),
            'path': path,
            'preview_path': shot.get('preview_asset'),
        },
        'transform': {
            'media_start': float(shot.get('aroll_media_start') or shot.get('media_start') or 0),
            'camera': shot.get('camera'),
            'motion_plan': copy.deepcopy(shot.get('motion_plan')),
            'evidence_focus': copy.deepcopy(shot.get('evidence_focus') or shot.get('evidence_crop')),
        },
        'status': status,
        'source': source,
    }


def build_visual_timeline(project):
    clips = [
        clip for clip in (
            _clip(project, shot, index)
            for index, shot in enumerate(project.get('shots') or [])
        ) if clip
    ]
    total = round(sum(clip['duration'] for clip in clips), 3)
    return {
        'schema_version': SCHEMA_VERSION,
        'project_id': project.get('id'),
        'revision': project.get('revision'),
        'duration': total,
        'clips': clips,
    }


def sync_visual_timeline(project):
    project['visual_timeline'] = build_visual_timeline(project)
    return project['visual_timeline']


def validate_visual_timeline(project):
    timeline = build_visual_timeline(project)
    cursor = 0.0
    for clip in timeline['clips']:
        if abs(float(clip['start']) - cursor) > .002 or float(clip['duration']) <= 0:
            raise ValueError('统一视觉时间线存在空隙、重叠或无效时长')
        cursor += float(clip['duration'])
    if abs(cursor - float(project.get('duration') or cursor)) > .002:
        raise ValueError('统一视觉时间线未覆盖完整音频')
    project['visual_timeline'] = timeline
    return timeline
