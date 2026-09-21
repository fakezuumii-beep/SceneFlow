"""A-roll provider registry and selection facade."""
from __future__ import annotations
from .musetalk import MuseTalkProvider
from .latentsync import LatentSyncProvider
from .wav2lip import Wav2LipProvider
from .comfyui import ComfyUIProvider
from .infinitetalk import InfiniteTalkProvider
from .autodl_h3 import AutoDLH3Provider
from .external_api import ExternalApiProvider

PROVIDERS = {
    'infinitetalk': InfiniteTalkProvider,
    'autodl_h3': AutoDLH3Provider,
    'latentsync': LatentSyncProvider,
    'musetalk': MuseTalkProvider,
    'wav2lip': Wav2LipProvider,
    'comfyui': ComfyUIProvider,
    'external_api': ExternalApiProvider,
}


def provider_id(settings):
    mode = str(settings.get('aroll_provider') or 'musetalk').strip().lower()
    if mode == 'custom': return str(settings.get('aroll_custom_type') or 'comfyui').strip().lower()
    return mode


def get_aroll_provider(settings):
    selected = provider_id(settings)
    try: cls = PROVIDERS[selected]
    except KeyError: raise ValueError('请选择支持的 A-roll 人物口型方案') from None
    return cls(settings)


def project_aroll_settings(settings, project=None):
    """Apply an episode's provider choice without copying shared credentials."""
    result = dict(settings)
    selected = str((project or {}).get('aroll_provider_id') or '').strip().lower()
    if selected:
        result['aroll_provider'] = selected
    return result


def get_project_aroll_provider(settings, project):
    return get_aroll_provider(project_aroll_settings(settings, project))


def shot_aroll_settings(settings, shot, project=None):
    """Overlay safe per-shot choices without copying credentials into a project."""
    result = project_aroll_settings(settings, project)
    config = shot.get('aroll_config') or {}
    selected = str(config.get('provider') or 'global')
    if selected != 'global':
        result['aroll_provider'] = selected
    if config.get('resolution'):
        result['aroll_autodl_resolution'] = config['resolution']
    if config.get('batch_size'):
        result['aroll_batch_size'] = int(config['batch_size'])
    if config.get('positive_prompt'):
        result['aroll_infinitetalk_positive_prompt'] = str(config['positive_prompt']).strip()
    if config.get('negative_prompt'):
        result['aroll_infinitetalk_negative_prompt'] = str(config['negative_prompt']).strip()
    return result


def get_shot_aroll_provider(settings, shot, project=None):
    return get_aroll_provider(shot_aroll_settings(settings, shot, project))


def decorate_project(project, settings):
    """Expose the effective provider/readiness for each A-roll shot."""
    project_provider = get_project_aroll_provider(settings, project)
    project = project_provider.decorate(project)
    for shot in project.get('shots', []):
        if shot.get('kind') != 'A':
            continue
        provider = get_shot_aroll_provider(settings, shot, project)
        shot['aroll_ready'] = provider.is_ready(project, shot)
        shot['aroll_effective_provider'] = {
            'id': provider.id, 'name': provider.name, 'short_name': provider.short_name,
        }
    return project
