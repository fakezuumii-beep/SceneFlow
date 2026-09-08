"""A-roll provider registry and selection facade."""
from __future__ import annotations
from .musetalk import MuseTalkProvider
from .wav2lip import Wav2LipProvider
from .comfyui import ComfyUIProvider
from .external_api import ExternalApiProvider

PROVIDERS = {
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
