"""Provider selection around the existing stable stock-video implementation."""
from __future__ import annotations
import requests
from . import BROLL_PROVIDERS


def resolve_broll_config(settings, require_key=False):
    provider = str(settings.get('broll_provider') or 'pexels').strip().lower()
    if provider not in BROLL_PROVIDERS:
        raise ValueError('请选择支持的 B-roll 素材服务')
    key_name = provider + '_api_key'
    api_key = str(settings.get(key_name) or '')
    if require_key and not api_key:
        raise ValueError(f'还差一步：需要配置 B-roll 素材服务（{BROLL_PROVIDERS[provider]["name"]} API Key）')
    return {'provider': provider, 'name': BROLL_PROVIDERS[provider]['name'], 'api_key': api_key, 'key_name': key_name}


def test_connection(settings):
    cfg = resolve_broll_config(settings, require_key=True)
    try:
        if cfg['provider'] == 'pexels':
            response = requests.get('https://api.pexels.com/videos/search', params={'query': 'nature', 'per_page': 1},
                                    headers={'Authorization': cfg['api_key']}, timeout=(8, 20))
        else:
            response = requests.get('https://pixabay.com/api/videos/', params={'key': cfg['api_key'], 'q': 'nature', 'per_page': 3}, timeout=(8, 20))
    except requests.RequestException as exc:
        raise ValueError(f'{cfg["name"]} 服务无法访问，请检查网络') from exc
    if response.status_code in (400, 401, 403):
        raise ValueError(f'{cfg["name"]} API Key 无效或没有权限')
    if response.status_code >= 400:
        raise ValueError(f'{cfg["name"]} 暂时无法连接（HTTP {response.status_code}）')
    return {'ok': True, 'message': f'{cfg["name"]} 连接正常'}
