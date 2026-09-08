"""Resolve global LLM settings into one provider-neutral request config."""
from __future__ import annotations
from urllib.parse import urlsplit
import requests
from . import LLM_PROVIDERS


def resolve_llm_config(settings, require_key=False):
    provider = str(settings.get('llm_provider') or 'deepseek').strip().lower()
    if provider not in LLM_PROVIDERS:
        raise ValueError('请选择支持的分镜 AI 服务商')
    preset = LLM_PROVIDERS[provider]
    if provider == 'custom':
        name = str(settings.get('llm_custom_name') or '自定义模型服务').strip()[:80]
        base_url = str(settings.get('llm_custom_base_url') or '').strip().rstrip('/')
        model = str(settings.get('llm_custom_model') or '').strip()
        if not base_url.startswith(('https://', 'http://')) or not urlsplit(base_url).netloc:
            raise ValueError('请填写有效的自定义 API 地址')
        if not model:
            raise ValueError('请填写自定义模型名称')
    else:
        name, base_url, model = preset['name'], preset['base_url'], preset['model']
    api_key = str(settings.get('llm_api_key') or '')
    if require_key and not api_key:
        raise ValueError(f'还差一步：需要配置分镜 AI（{name} API Key）')
    return {
        'provider': provider, 'name': name, 'base_url': base_url, 'model': model,
        'api_key': api_key, 'type': preset['type'],
        'request_options': {'thinking': {'type': 'disabled'}} if provider == 'deepseek' else {},
    }


def test_connection(settings):
    cfg = resolve_llm_config(settings, require_key=True)
    url = cfg['base_url'].rstrip('/') + '/models'
    headers = {'Authorization': 'Bearer ' + cfg['api_key']}
    try:
        response = requests.get(url, headers=headers, timeout=(8, 20))
    except requests.RequestException as exc:
        raise ValueError(f'{cfg["name"]} 服务无法访问，请检查网络和 API 地址') from exc
    if response.status_code in (401, 403):
        raise ValueError(f'{cfg["name"]} API Key 无效或没有权限')
    if response.status_code >= 400:
        raise ValueError(f'{cfg["name"]} 暂时无法连接（HTTP {response.status_code}）')
    return {'ok': True, 'message': f'{cfg["name"]} 连接正常'}
