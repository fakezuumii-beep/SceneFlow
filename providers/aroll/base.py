"""Small, stable interface implemented by every A-roll provider."""
from __future__ import annotations
import hashlib, json


class ArollProvider:
    id = ''
    name = ''
    short_name = ''
    runtime = ''
    version = '1'

    def __init__(self, settings):
        self.settings = settings

    def status(self, check_online=False):
        raise NotImplementedError

    def validate_config(self):
        return True

    def cache_identity(self):
        return {'provider': self.id, 'provider_version': self.version, 'model': None, 'workflow_hash': None}

    def signature(self, project, shot):
        import aroll
        return aroll.signature(project, shot, self.cache_identity())

    def is_ready(self, project, shot):
        import core
        return bool(shot.get('aroll_asset') and shot.get('aroll_signature') == self.signature(project, shot)
                    and (core.project_dir(project['id']) / shot['aroll_asset']).is_file())

    def decorate(self, project):
        import core
        folder = core.project_dir(project['id'])
        project['host_asset'] = core.host_image(project).relative_to(folder).as_posix()
        media = core.host_media(project)
        project['host_media_asset'] = media.relative_to(folder).as_posix()
        project['host_media_kind'] = 'video' if media.suffix.lower() in ('.mp4','.mov','.mkv','.webm','.m4v') else 'image'
        project['aroll_provider'] = {'id': self.id, 'name': self.name, 'short_name': self.short_name, **self.status()}
        for shot in project.get('shots', []):
            if shot.get('kind') == 'A': shot['aroll_ready'] = self.is_ready(project, shot)
        return project

    def generate(self, pid, shot_id=None):
        raise ValueError(f'{self.name} 当前尚未准备好，请前往「连接与设置」')

    def cancel(self, pid):
        return None

    @staticmethod
    def workflow_hash(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
