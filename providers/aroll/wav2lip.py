from __future__ import annotations
from pathlib import Path
from .base import ArollProvider


class Wav2LipProvider(ArollProvider):
    id = 'wav2lip'
    name = 'Wav2Lip'
    short_name = 'Wav2Lip · 轻量'
    runtime = 'local'
    version = 'wav2lip-provider-v1'

    def status(self, check_online=False):
        root = Path(__file__).resolve().parents[2] / 'engines' / 'Wav2Lip'
        installed = (root / 'checkpoints' / 'wav2lip_gan.pth').is_file()
        message = '已检测到模型，但 SOLO 生成适配尚未开放' if installed else '尚未安装 · 仅限个人 / 研究 / 非商业用途'
        return {'ready': False, 'installed': installed, 'message': message, 'license_notice': '仅限个人 / 研究 / 非商业用途'}

    def cache_identity(self):
        return {'provider': self.id, 'provider_version': self.version, 'model': 'wav2lip_gan', 'workflow_hash': None}

    def generate(self, pid, shot_id=None):
        raise ValueError('Wav2Lip 自动安装与生成尚未开放；请选择 MuseTalk，或在后续版本安装轻量组件')
