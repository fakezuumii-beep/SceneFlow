from __future__ import annotations
import requests
from .base import ArollProvider


class ExternalApiProvider(ArollProvider):
    id = 'external_api'
    name = '在线 API'
    short_name = '在线 API'
    runtime = 'online'
    version = 'solo-external-aroll-v1'

    def validate_config(self):
        for key,label in (('aroll_external_name','服务名称'),('aroll_external_url','API 地址'),('aroll_external_model','模型 / 工作流 ID')):
            if not str(self.settings.get(key) or '').strip(): raise ValueError(f'请填写在线 A-roll 的{label}')
        if not str(self.settings['aroll_external_url']).startswith(('http://','https://')): raise ValueError('请填写有效的在线 A-roll API 地址')
        if not self.settings.get('aroll_external_api_key'): raise ValueError('请填写在线 A-roll API Key')
        return True

    def status(self, check_online=False):
        try: self.validate_config()
        except ValueError as exc: return {'ready': False, 'installed': False, 'message': str(exc)}
        return {'ready': False, 'installed': True, 'configured': True, 'message': '配置已保存；生成适配将在后续版本开放'}

    def test_connection(self):
        self.validate_config();headers={'Authorization':'Bearer '+self.settings['aroll_external_api_key']}
        try: response=requests.get(str(self.settings['aroll_external_url']).rstrip('/')+'/status',headers=headers,timeout=(5,12))
        except requests.RequestException as exc: raise ValueError('在线 A-roll 服务无法访问，请检查网络和 API 地址') from exc
        if response.status_code in (401,403):raise ValueError('在线 A-roll API Key 无效或没有权限')
        if response.status_code>=400:raise ValueError(f'在线 A-roll 服务暂时不可用（HTTP {response.status_code}）')
        return {'ok':True,'message':'在线 A-roll 服务连接正常'}

    def cache_identity(self):
        return {'provider': self.id, 'provider_version': self.version,
                'model': self.settings.get('aroll_external_model'), 'workflow_hash': None,
                'service': self.settings.get('aroll_external_name'), 'url': self.settings.get('aroll_external_url')}

    def generate(self, pid, shot_id=None):
        raise ValueError('在线 A-roll 连接校验已可用；SOLO External A-roll 生成协议将在后续版本开放')
