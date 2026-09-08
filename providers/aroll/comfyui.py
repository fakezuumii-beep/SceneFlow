from __future__ import annotations
import requests
from .base import ArollProvider


class ComfyUIProvider(ArollProvider):
    id = 'comfyui'
    name = 'ComfyUI'
    short_name = 'ComfyUI · 自定义'
    runtime = 'custom'
    version = 'comfyui-workflow-provider-v1'

    def validate_config(self):
        url = str(self.settings.get('aroll_comfyui_url') or '').strip()
        if not url.startswith(('http://', 'https://')): raise ValueError('请填写有效的 ComfyUI 地址')
        if not self.settings.get('aroll_comfyui_workflow_hash'): raise ValueError('请导入 workflow_api.json')
        for key, label in (('aroll_person_node','人物输入节点'),('aroll_audio_node','音频输入节点'),('aroll_output_node','输出节点')):
            if not str(self.settings.get(key) or '').strip(): raise ValueError(f'请填写{label}')
        return True

    def status(self, check_online=False):
        try: self.validate_config()
        except ValueError as exc: return {'ready': False, 'installed': False, 'message': str(exc)}
        return {'ready': False, 'installed': True, 'configured': True, 'message': '配置已保存；生成适配将在后续版本开放'}

    def test_connection(self):
        self.validate_config(); url=str(self.settings['aroll_comfyui_url']).rstrip('/')+'/system_stats'
        try: response=requests.get(url,timeout=(5,12))
        except requests.RequestException as exc: raise ValueError('ComfyUI 服务无法访问，请确认地址和启动状态') from exc
        if response.status_code!=200: raise ValueError(f'ComfyUI 暂时无法连接（HTTP {response.status_code}）')
        return {'ok':True,'message':'ComfyUI 连接正常'}

    def cache_identity(self):
        return {'provider': self.id, 'provider_version': self.version, 'model': None,
                'workflow_hash': self.settings.get('aroll_comfyui_workflow_hash'),
                'nodes': [self.settings.get('aroll_person_node'),self.settings.get('aroll_audio_node'),self.settings.get('aroll_output_node')]}

    def generate(self, pid, shot_id=None):
        raise ValueError('ComfyUI 连接与工作流校验已可用；自动注入和取回视频将在后续版本开放')
