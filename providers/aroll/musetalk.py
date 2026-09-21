from __future__ import annotations
from .base import ArollProvider


class MuseTalkProvider(ArollProvider):
    id = 'musetalk'
    name = 'MuseTalk 1.5'
    short_name = 'MuseTalk 1.5 · 高质量'
    runtime = 'local'
    version = 'musetalk15-provider-v2'

    def runtime_config(self):
        quality = str(self.settings.get('aroll_musetalk_quality') or 'highest')
        profiles = {
            'highest': {'precision': 'float32', 'blend': 'face_parser', 'crf': 14},
            'balanced': {'precision': 'float16', 'blend': 'face_parser', 'crf': 16},
            'compatible': {'precision': 'float16', 'blend': 'ellipse', 'crf': 18},
        }
        result = dict(profiles.get(quality, profiles['highest']))
        result.update(
            quality=quality,
            parsing_mode=str(self.settings.get('aroll_musetalk_parsing_mode') or 'jaw'),
            extra_margin=int(self.settings.get('aroll_musetalk_extra_margin', 10)),
            left_cheek_width=int(self.settings.get('aroll_musetalk_left_cheek_width', 90)),
            right_cheek_width=int(self.settings.get('aroll_musetalk_right_cheek_width', 90)),
            audio_padding_left=int(self.settings.get('aroll_musetalk_audio_padding_left', 2)),
            audio_padding_right=int(self.settings.get('aroll_musetalk_audio_padding_right', 2)),
            face_smoothing='median-5',
        )
        return result

    def status(self, check_online=False):
        import aroll
        value = aroll.installation_status(check_online)
        return {'ready': value['installed'], 'installed': value['installed'], 'message': value['message']}

    def cache_identity(self):
        import aroll
        return {'provider': self.id, 'provider_version': self.version, 'model': 'MuseTalk 1.5',
                'adapter': aroll.VIDEO_ADAPTER_VERSION + '|' + aroll.ADAPTER_VERSION,
                'workflow_hash': None, 'quality_config': self.runtime_config()}

    def generate(self, pid, shot_id=None):
        import aroll
        return aroll.generate(pid, shot_id, self.cache_identity(), self.runtime_config())
