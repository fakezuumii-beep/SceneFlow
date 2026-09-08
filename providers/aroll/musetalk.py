from __future__ import annotations
from .base import ArollProvider


class MuseTalkProvider(ArollProvider):
    id = 'musetalk'
    name = 'MuseTalk 1.5'
    short_name = 'MuseTalk 1.5 · 本地'
    runtime = 'local'
    version = 'musetalk15-provider-v1'

    def status(self, check_online=False):
        import aroll
        value = aroll.installation_status(check_online)
        return {'ready': value['installed'], 'installed': value['installed'], 'message': value['message']}

    def cache_identity(self):
        import aroll
        return {'provider': self.id, 'provider_version': self.version, 'model': 'MuseTalk 1.5',
                'adapter': aroll.VIDEO_ADAPTER_VERSION + '|' + aroll.ADAPTER_VERSION, 'workflow_hash': None}

    def generate(self, pid, shot_id=None):
        import aroll
        return aroll.generate(pid, shot_id, self.cache_identity())
