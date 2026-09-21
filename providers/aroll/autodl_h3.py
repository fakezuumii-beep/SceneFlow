"""AutoDL MiniMax H3 image+audio lip-sync provider.

The provider uses a bounded six-worker paid queue and promotes each completed
shot independently.  A stopped or restarted workbench can therefore resume
polling an accepted task instead of paying for a duplicate.
"""
from __future__ import annotations

import base64
import concurrent.futures
import copy
import hashlib
import json
import math
import mimetypes
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .base import ArollProvider
from .h3_prompts import ArollPromptBuilder, H3_PROMPTS


WORKFLOW_ID = 'minimax_h3_image_audio_to_video_v2_15s'
LEGACY_WORKFLOW_ID = 'minimax_h3_image_audio_to_video'
API_BASE = 'https://www.autodl.art/api/v1/comfyui/comfyui_workflow'
FPS = 25
MAX_SECONDS = 15
POLL_SECONDS = 2
POLL_TIMEOUT = 2 * 3600
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_CONCURRENCY = 6
GLOBAL_TASK_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENCY)
RESOLUTIONS = {
    '480p竖': (480, 832),
    '768p竖': (768, 1344),
    '1080p竖': (1080, 1920),
    '480p横': (832, 480),
    '768p横': (1344, 768),
    '1080p横': (1920, 1080),
}
CLOUD_RESOLUTION = {
    '480p竖':'480p竖','768p竖':'768p竖','1080p竖':'768p竖',
    '480p横':'480p横','768p横':'768p横','1080p横':'768p横',
}
SUCCESS = {'SUCCESS', 'SUCCEEDED', 'COMPLETED', 'COMPLETE'}
FAILED = {'FAILED', 'ERROR', 'CANCELLED', 'CANCELED'}


class _BatchProgress:
    """Coalesce concurrent poll updates so project progress never moves backwards."""

    def __init__(self, pid, total):
        self.pid = pid
        self.total = max(1, total)
        self.active = set()
        self.completed = 0
        self.last_report = 0.0
        self.lock = threading.Lock()

    def _snapshot(self, detail, force=False):
        now = time.monotonic()
        with self.lock:
            if not force and now - self.last_report < 1:
                return None
            self.last_report = now
            percent = 5 + 85 * self.completed / self.total
            message = (f'H3 最多 {MAX_CONCURRENCY} 路并发 · 已完成 {self.completed}/{self.total}'
                       f' · 云端运行 {len(self.active)} 条')
            if detail:
                message += f' · {detail}'
            return percent, message

    def report(self, ordinal, detail='', force=False):
        snapshot = self._snapshot(detail, force)
        if snapshot:
            _progress(self.pid, 'MiniMax H3 对口型', *snapshot, finish_paid_task=True)

    def start(self, ordinal):
        with self.lock:
            self.active.add(ordinal)
        self.report(ordinal, '正在提交或续查任务', force=True)

    def complete(self, ordinal):
        with self.lock:
            self.active.discard(ordinal)
            self.completed += 1
        self.report(ordinal, '已下载并校验一个片段', force=True)

    def fail(self, ordinal):
        with self.lock:
            self.active.discard(ordinal)
        self.report(ordinal, '一个片段未完成，正在收尾其他已提交任务', force=True)


def _stamp(path: Path):
    stat = path.stat()
    return [str(path), stat.st_size, stat.st_mtime_ns]


def _json(path: Path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _data_url(path: Path, mime_type=None):
    mime = mime_type or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def _progress(pid, stage, percent, message, finish_paid_task=False):
    """Keep reporting an already-billed task even after the user asks to stop."""
    import core as c
    if not finish_paid_task or not c.ACTIVE.get(pid, {}).get('cancel'):
        return c.progress(pid, stage, percent, message)
    with c.LOCK:
        project = c.read_project(pid)
        project['job'].update(stage=stage, progress=round(percent), message=message)
        c.save_project(project)


def _response_data(response):
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f'AutoDL 返回了无法解析的内容（HTTP {response.status_code}）') from exc
    if response.status_code in (401, 403):
        raise ValueError('AutoDL Token 无效或没有 ComfyUI 工作流权限')
    if response.status_code >= 400:
        detail = payload.get('msg') or payload.get('message') or payload.get('detail') or response.reason
        raise RuntimeError(f'AutoDL 请求失败：{detail}')
    code = str(payload.get('code') or 'Success').lower()
    if code not in ('success', '200', '0'):
        raise RuntimeError('AutoDL 请求失败：' + str(payload.get('msg') or payload.get('message') or code))
    data = payload.get('data')
    if not isinstance(data, dict):
        raise RuntimeError('AutoDL 返回中缺少任务数据')
    return data


def _result_url(data):
    results = data.get('results')
    if not isinstance(results, list):
        result = data.get('result')
        results = result if isinstance(result, list) else ([result] if isinstance(result, dict) else [])
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get('url') or item.get('download_url') or '').strip()
        kind = str(item.get('type') or item.get('file_type') or '').lower()
        if url and ('video' in kind or kind == 'mp4' or url.lower().split('?', 1)[0].endswith('.mp4')):
            return url
    return None


class AutoDLH3Provider(ArollProvider):
    id = 'autodl_h3'
    name = 'MiniMax H3 自动对口型'
    short_name = 'H3 · 云端口型'
    runtime = 'online'
    version = 'autodl-h3-lipsync-v3-prompted'

    def validate_config(self):
        token = str(self.settings.get('aroll_autodl_api_key') or '').strip()
        if len(token) < 12 or '*' in token:
            raise ValueError('请填写完整的 AutoDL ComfyUI Token')
        resolution = str(self.settings.get('aroll_autodl_resolution') or '768p横')
        if resolution not in RESOLUTIONS:
            raise ValueError('请选择支持的 AutoDL H3 分辨率')
        if str(self.settings.get('aroll_autodl_cut_style') or 'steady') not in H3_PROMPTS:
            raise ValueError('请选择支持的 MiniMax H3 镜头风格')
        return True

    def status(self, check_online=False):
        try:
            self.validate_config()
        except ValueError as exc:
            return {'ready': False, 'installed': True, 'configured': False, 'message': str(exc)}
        resolution = self.settings.get('aroll_autodl_resolution') or '768p横'
        style={'steady':'固定长镜头','restrained':'克制切镜','free':'自由切镜'}[
            str(self.settings.get('aroll_autodl_cut_style') or 'steady')]
        return {'ready': True, 'installed': True, 'configured': True,
                'message': (f'AutoDL Token 已配置 · {resolution} · 最多 {MAX_CONCURRENCY} 路并发'
                            f' · {style} · H3 提示词工作流')}

    def test_connection(self):
        self.validate_config()
        return {'ok': True, 'message': '配置完整；为避免产生费用，首次生成时再由 AutoDL 验证 Token'}

    def cache_identity(self):
        return {'provider': self.id, 'provider_version': self.version,
                'model': 'MiniMax H3', 'workflow_hash': WORKFLOW_ID,
                'cut_style':str(self.settings.get('aroll_autodl_cut_style') or 'steady'),
                'resolution': self.settings.get('aroll_autodl_resolution') or '768p横'}

    def is_ready(self, project, shot):
        """Keep verified paid outputs valid across the forward-only workflow upgrade."""
        if super().is_ready(project,shot):return True
        import core as c
        provenance=shot.get('aroll_provenance') or {}
        asset=shot.get('aroll_asset')
        if provenance.get('provider')!=self.id or not asset:return False
        path=c.project_dir(project['id'])/asset
        if not path.is_file():return False
        try:source=c.host_image(project).relative_to(c.project_dir(project['id'])).as_posix()
        except (OSError,ValueError):return False
        return (provenance.get('source')==source and
                abs(float(provenance.get('audio_start',-1))-float(shot['start']))<.002 and
                abs(float(provenance.get('audio_end',-1))-float(shot['end']))<.002)

    def signature(self, project, shot):
        import core as c
        if not project.get('audio'):
            return ''
        identity = dict(self.cache_identity())
        if shot.get('aroll_config'):
            identity['shot_config'] = shot['aroll_config']
        content = [identity, _stamp(c.asset_path(project['id'], project['audio'])),
                   _stamp(c.host_image(project)), shot['start'], shot['end'], FPS]
        return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode()).hexdigest()[:24]

    def generate(self, pid, shot_id=None):
        self.validate_config()
        return generate(self, pid, shot_id)


def _audio_chunk(project, start, real_duration, api_duration, target):
    import core as c
    if target.is_file() and target.stat().st_size > 44:
        return
    temporary = target.with_suffix('.part.wav')
    audio_filter = f'atrim=duration={real_duration:.6f},apad=whole_dur={api_duration:.6f}'
    c.run([c.FFMPEG, '-y', '-v', 'error', '-ss', f'{start:.6f}', '-i',
           c.asset_path(project['id'], project['audio']), '-vn', '-af', audio_filter,
           '-t', f'{api_duration:.6f}', '-ac', '1', '-ar', '24000', '-c:a', 'pcm_s16le', temporary])
    if not temporary.is_file() or temporary.stat().st_size <= 44:
        raise RuntimeError('AutoDL H3 镜头音频截取失败')
    temporary.replace(target)


def _submit(provider, body):
    response = requests.post(f'{API_BASE}/{WORKFLOW_ID}',
                             headers={'Authorization': provider.settings['aroll_autodl_api_key'],
                                      'Content-Type': 'application/json'},
                             json=body, timeout=(30, 300))
    data = _response_data(response)
    task_id = str(data.get('task_id') or '').strip()
    if not task_id:
        raise RuntimeError('AutoDL 没有返回任务号')
    return data


def _query(provider, task_id):
    response = requests.get(f'{API_BASE}/result/{task_id}',
                            headers={'Authorization': provider.settings['aroll_autodl_api_key'],
                                     'Content-Type': 'application/json'},
                            timeout=(30, 90))
    return _response_data(response)


def _download(url, target):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError('AutoDL 返回了不安全的结果地址')
    temporary = target.with_suffix('.part.mp4')
    total = 0
    with requests.get(url, stream=True, allow_redirects=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        declared = int(response.headers.get('content-length') or 0)
        if declared > MAX_DOWNLOAD_BYTES:
            raise RuntimeError('AutoDL 返回的视频超过 2 GB，已停止下载')
        with temporary.open('wb') as stream:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise RuntimeError('AutoDL 返回的视频超过 2 GB，已停止下载')
                stream.write(chunk)
    if total == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError('AutoDL 返回了空的视频文件')
    temporary.replace(target)


def _collect(provider, pid, chunk, body, index, total, tracker=None, stage='MiniMax H3 对口型'):
    import core as c
    raw = chunk / 'raw.mp4'
    try:
        if raw.is_file() and any(s.get('codec_type') == 'video' for s in c.probe(raw).get('streams', [])):
            return raw
    except (OSError, ValueError, RuntimeError):
        raw.unlink(missing_ok=True)
    state_path = chunk / 'task.json'
    state = _json(state_path)
    task_id = str(state.get('task_id') or '')
    task_status = str(state.get('status') or '').upper()
    if not task_id or task_status in FAILED:
        if c.ACTIVE.get(pid, {}).get('cancel'):
            raise RuntimeError('已停止；尚未提交新的 AutoDL 付费任务')
        attempt = int(state.get('attempt') or 0) + 1
        try:
            data = _submit(provider, body)
        except requests.RequestException as exc:
            raise RuntimeError('AutoDL 提交失败，请检查网络后继续生成') from exc
        task_id = str(data['task_id'])
        state = {'task_id': task_id, 'status': str(data.get('status') or 'QUEUED').upper(),
                 'attempt': attempt, 'workflow_id': WORKFLOW_ID, 'created_at': time.time()}
        c.atomic_json(state_path, state)
    began = time.monotonic()
    failures = 0
    missing_url = 0
    while time.monotonic() - began < POLL_TIMEOUT:
        try:
            data = _query(provider, task_id)
            failures = 0
        except requests.RequestException as exc:
            failures += 1
            if failures >= 8:
                raise RuntimeError('AutoDL 查询连续失败；任务号已保留，可稍后继续生成') from exc
            time.sleep(min(15, POLL_SECONDS * failures))
            continue
        status = str(data.get('status') or '').upper()
        state.update(status=status or 'UNKNOWN', updated_at=time.time())
        c.atomic_json(state_path, state)
        if status in FAILED:
            detail = data.get('message') or data.get('msg') or data.get('error') or status
            raise RuntimeError('AutoDL H3 生成失败：' + str(detail))
        if status in SUCCESS:
            url = _result_url(data)
            if not url:
                missing_url += 1
                if missing_url >= 20:
                    raise RuntimeError('AutoDL 任务已完成但暂未返回视频地址；任务号已保留，可稍后继续生成')
                time.sleep(POLL_SECONDS)
                continue
            if tracker:
                tracker.report(index, f'正在下载结果 {index + 1}/{total}', force=True)
            else:
                _progress(pid, stage, 5 + 88 * index / max(1, total),
                          f'正在下载 AutoDL 结果 {index + 1}/{total}', finish_paid_task=True)
            try:
                _download(url, raw)
            except requests.RequestException as exc:
                raise RuntimeError('AutoDL 结果下载失败；任务号已保留，可继续生成') from exc
            try:
                info = c.probe(raw)
            except (ValueError, RuntimeError, OSError) as exc:
                raw.unlink(missing_ok=True)
                raise RuntimeError('AutoDL 返回的视频无法解码；任务号已保留') from exc
            if not any(stream.get('codec_type') == 'video' for stream in info.get('streams', [])):
                raw.unlink(missing_ok=True)
                raise RuntimeError('AutoDL 返回结果中没有视频轨')
            state.update(status='DOWNLOADED', downloaded_at=time.time())
            c.atomic_json(state_path, state)
            return raw
        elapsed = data.get('duration')
        suffix = f' · 已运行 {elapsed} 秒' if elapsed is not None else ''
        if c.ACTIVE.get(pid, {}).get('cancel'):
            suffix += ' · 已提交任务不能取消，下载后将停止'
        if tracker:
            tracker.report(index, f'云端生成 {index + 1}/{total}{suffix}')
        else:
            _progress(pid, stage, 5 + 85 * index / max(1, total),
                      f'AutoDL 云端生成 {index + 1}/{total}{suffix}', finish_paid_task=True)
        time.sleep(POLL_SECONDS)
    raise RuntimeError('AutoDL H3 等待超过两小时；任务号已保留，可稍后继续生成')


def _normalize(raw, target, frames, size):
    import aroll
    import core as c
    if aroll.valid_chunk(target, frames):
        return
    temporary = target.with_suffix('.part.mp4')
    width, height = size
    filters = (f'fps={FPS},scale={width}:{height}:force_original_aspect_ratio=increase,'
               f'crop={width}:{height},setsar=1,tpad=stop_mode=clone:stop_duration=1,'
               f'trim=start_frame=0:end_frame={frames},setpts=PTS-STARTPTS')
    c.run([c.FFMPEG, '-y', '-v', 'error', '-i', raw, '-an', '-vf', filters,
           '-frames:v', str(frames), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
           '-pix_fmt', 'yuv420p', '-threads', '4', '-movflags', '+faststart', temporary])
    if not aroll.valid_chunk(temporary, frames):
        raise RuntimeError('AutoDL H3 视频帧数校验失败，原始下载已保留')
    temporary.replace(target)


def _assemble(chunks, target, frames):
    import aroll
    import core as c
    if aroll.valid_chunk(target, frames):
        return
    temporary = target.with_suffix('.part.mp4')
    if len(chunks) == 1:
        c.run([c.FFMPEG, '-y', '-v', 'error', '-i', chunks[0], '-an', '-c:v', 'copy',
               '-movflags', '+faststart', temporary])
    else:
        listing = target.with_suffix('.concat.txt')
        listing.write_text('\n'.join("file '" + str(path.resolve()).replace('\\', '/').replace("'", "'\\''") + "'"
                                     for path in chunks), encoding='utf-8')
        try:
            c.run([c.FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', listing,
                   '-an', '-c:v', 'copy', '-movflags', '+faststart', temporary])
        finally:
            listing.unlink(missing_ok=True)
    if not aroll.valid_chunk(temporary, frames):
        raise RuntimeError('AutoDL H3 分段拼接校验失败，已保留下载结果')
    temporary.replace(target)


def _frame_chunks(total_frames):
    count = max(1, math.ceil(total_frames / (MAX_SECONDS * FPS)))
    base, remainder = divmod(total_frames, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _collapse_aroll_runs(project):
    """Give each continuous A-roll run to H3 instead of pre-cutting it locally."""
    source = project.get('shots', [])
    segments = project.get('segments', [])
    output = []
    id_map = {}
    changed = False
    index = 0
    while index < len(source):
        if source[index].get('kind') != 'A':
            output.append(source[index])
            index += 1
            continue
        run = [source[index]]
        index += 1
        while (index < len(source) and source[index].get('kind') == 'A' and
               (source[index].get('aroll_config') or {}) == (run[-1].get('aroll_config') or {}) and
               abs(float(source[index]['start']) - float(run[-1]['end'])) <= .002):
            run.append(source[index])
            index += 1
        first = run[0]
        native = (len(run) == 1 and first.get('aroll_edit_mode') == 'provider_native' and
                  first.get('visual_change') == 'h3_native' and first.get('camera') is None and
                  first.get('motion') is None)
        if native:
            id_map[first['id']] = first['id']
            output.append(first)
            continue
        changed = True
        merged = copy.deepcopy(first)
        preserve_current = (len(run) == 1 and
                            first.get('aroll_provenance', {}).get('provider') == 'autodl_h3')
        start, end = float(run[0]['start']), float(run[-1]['end'])
        ids = [item.get('id') for item in segments
               if float(item.get('end', item.get('start', 0))) > start + .001 and
               float(item.get('start', 0)) < end - .001]
        texts = [str(item.get('text', '')) for item in segments if item.get('id') in ids]
        narrative_ids = list(dict.fromkeys(nid for item in run for nid in item.get('narrative_ids', [])))
        histories = []
        for item in run:
            histories.extend(copy.deepcopy(item.get('aroll_history', [])))
            if item.get('aroll_asset') and not preserve_current:
                histories.append({'asset': item['aroll_asset'], 'signature': item.get('aroll_signature'),
                                  'provider': item.get('aroll_provenance', {}).get('provider')})
            id_map[item['id']] = merged['id']
        unique_history = []
        seen = set()
        for item in histories:
            key = (item.get('asset'), item.get('signature'))
            if item.get('asset') and key not in seen:
                seen.add(key)
                unique_history.append(item)
        merged.update(start=round(start, 3), end=round(end, 3),
                      narrative_ids=narrative_ids, text=''.join(texts) or ''.join(str(item.get('text', '')) for item in run),
                      visual_part=1, visual_parts=1, cut_score=None, cut_reason='',
                      editorial_review=('连续 A-roll 超过 15 秒：生成时按最少段数拆成不超过 15 秒的 H3 片段，'
                                        '片段之间使用程序硬切' if end-start > MAX_SECONDS else None),
                      camera=None, motion=None, visual_change='h3_native',
                      aroll_edit_mode='provider_native', keywords=[])
        if ids:
            merged['from'], merged['to'] = ids[0], ids[-1]
        if unique_history:
            merged['aroll_history'] = unique_history
        if not preserve_current:
            for key in ('aroll_asset', 'aroll_media_start', 'aroll_signature', 'aroll_status',
                        'aroll_error', 'aroll_provenance', 'aroll_ready'):
                merged.pop(key, None)
        output.append(merged)
    if changed:
        project['shots'] = output
    return changed, id_map


def _api_duration(real_duration):
    """AutoDL's workflow duration widget accepts whole seconds only."""
    return max(1, min(MAX_SECONDS, math.ceil(float(real_duration) - 1e-9)))


def _prompt(provider):
    return ArollPromptBuilder().build(provider.settings)


def _run_bounded(items, worker, limit, should_stop=lambda: False):
    """Run a bounded paid queue and stop scheduling new work after the first error."""
    items = list(items)
    results = {}
    errors = []
    scheduled = 0
    stopped = False
    futures = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, limit)) as executor:
        while futures or (scheduled < len(items) and not stopped):
            while len(futures) < limit and scheduled < len(items) and not stopped:
                if should_stop():
                    stopped = True
                    break
                index = scheduled
                futures[executor.submit(worker, items[index])] = index
                scheduled += 1
            if not futures:
                break
            done, _ = concurrent.futures.wait(
                futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                index = futures.pop(future)
                try:
                    results[index] = future.result()
                except Exception as exc:
                    errors.append((index, exc))
                    stopped = True
    return results, errors, scheduled


def _promote_shot(provider, pid, folder, image, resolution, plan, chunk_results):
    import core as c
    shot = plan['shot']
    normalized = [item['normalized'] for item in chunk_results]
    task_ids = [item['task_id'] for item in chunk_results if item['task_id']]
    asset = folder / 'assets' / f'aroll-h3-{plan["asset_key"]}.mp4'
    _assemble(normalized, asset, plan['total_frames'])
    info = c.probe(asset)
    relative = asset.relative_to(folder).as_posix()
    with c.LOCK:
        current = c.read_project(pid)
        target = next(item for item in current['shots'] if item['id'] == shot['id'])
        if target.get('aroll_asset') and target['aroll_asset'] != relative:
            target.setdefault('aroll_history', []).append(
                {'asset': target['aroll_asset'], 'signature': target.get('aroll_signature')})
        target.update(aroll_asset=relative, aroll_media_start=0, aroll_signature=plan['signature'],
                      aroll_status='ready', aroll_error=None,
                      aroll_provenance={'provider': provider.id, 'engine': provider.name,
                      'runtime': 'online', 'provider_version': provider.version,
                      'model': 'MiniMax H3', 'workflow_id': WORKFLOW_ID,
                      'resolution': resolution, 'cloud_resolution':CLOUD_RESOLUTION[resolution],
                      'cut_style':str(provider.settings.get('aroll_autodl_cut_style') or 'steady'),
                      'prompt_policy':'stable-podcast-camera-v1',
                      'task_ids': task_ids, 'fps': FPS,
                      'concurrency_limit': MAX_CONCURRENCY,
                      'duration': plan['total_frames'] / FPS,
                      'continuous_asset_duration': info['duration'],
                       'cut_policy': 'h3-native-up-to-15s-then-program-hard-cut',
                      'continuity_policy': 'same-reference-background-across-native-cuts-v1',
                       'h3_native_max_seconds': MAX_SECONDS,
                      'program_hard_cuts': max(0, len(normalized) - 1),
                      'chunk_durations': [round(c.probe(path)['duration'], 3) for path in normalized],
                      'source': image.relative_to(folder).as_posix(), 'source_kind': 'image',
                      'audio':current.get('audio'),
                      'audio_start': shot['start'], 'audio_end': shot['end'],
                      'remote_inputs': ['host_image', 'shot_audio'], 'billing': 'per generated second'})
        current['revision'] += 1
        c.save_project(current)


def generate(provider, pid, shot_id=None):
    import core as c
    project = c.read_project(pid)
    changed, id_map = _collapse_aroll_runs(project)
    if changed:
        project['revision'] += 1
        c.validate_timeline(project['shots'], project['duration'])
        c.save_project(project)
    if shot_id:
        shot_id = id_map.get(shot_id, shot_id)
    shots = [shot for shot in project.get('shots', []) if shot.get('kind') == 'A']
    if shot_id and not any(shot.get('id') == shot_id for shot in shots):
        raise ValueError('未找到选中的 A-roll 镜头')
    pending = [shot for shot in shots if (shot.get('id') == shot_id if shot_id else not provider.is_ready(project, shot))]
    if not pending:
        return
    c.validate_timeline(project['shots'], project['duration'])
    folder = c.project_dir(pid)
    image = c.host_image(project)
    resolution = provider.settings.get('aroll_autodl_resolution') or '768p横'
    cloud_resolution=CLOUD_RESOLUTION[resolution]
    size = RESOLUTIONS[resolution]
    total_chunks = sum(len(_frame_chunks(max(1, round((shot['end'] - shot['start']) * FPS)))) for shot in pending)
    image_data = _data_url(image)
    plans = []
    jobs = []
    for shot_index, shot in enumerate(pending):
        signature = provider.signature(project, shot)
        suffix = '-' + uuid.uuid4().hex[:6] if shot_id else ''
        asset_key = signature + suffix
        shot_cache = folder / 'aroll-cache' / ('autodl-h3-' + asset_key)
        shot_cache.mkdir(parents=True, exist_ok=True)
        total_frames = max(1, round((float(shot['end']) - float(shot['start'])) * FPS))
        offset_frames = 0
        plan = {'shot': shot, 'shot_index': shot_index, 'signature': signature,
                'asset_key': asset_key, 'total_frames': total_frames, 'jobs': []}
        for chunk_index, frames in enumerate(_frame_chunks(total_frames)):
            cache = shot_cache / f'chunk-{chunk_index + 1:03d}'
            cache.mkdir(exist_ok=True)
            real_duration = frames / FPS
            api_duration = _api_duration(real_duration)
            audio = cache / 'audio.wav'
            start = float(shot['start']) + offset_frames / FPS
            _audio_chunk(project, start, real_duration, api_duration, audio)
            job = {'ordinal': len(jobs), 'shot_id': shot['id'], 'chunk_index': chunk_index,
                   'frames': frames, 'cache': cache, 'audio': audio,
                   'api_duration': api_duration}
            jobs.append(job)
            plan['jobs'].append(job)
            offset_frames += frames
        plans.append(plan)

    tracker = _BatchProgress(pid, total_chunks)

    def run_chunk(job):
        acquired=False
        try:
            while not acquired:
                if c.ACTIVE.get(pid, {}).get('cancel'):
                    raise RuntimeError('已停止；尚未提交新的 AutoDL 付费任务')
                acquired=GLOBAL_TASK_SLOTS.acquire(timeout=.5)
            tracker.start(job['ordinal'])
            body = {'resolution': cloud_resolution,
                    'ref_audio_0': _data_url(job['audio'], 'audio/wav'),
                    'ref_image_0': image_data, 'duration': job['api_duration'],
                    'prompt':_prompt(provider)}
            raw = _collect(provider, pid, job['cache'], body, job['ordinal'], total_chunks, tracker)
            task_id = str(_json(job['cache'] / 'task.json').get('task_id') or '')
            output = job['cache'] / 'normalized.mp4'
            _normalize(raw, output, job['frames'], size)
            result = {'normalized': output, 'task_id': task_id}
            tracker.complete(job['ordinal'])
            return result
        except Exception:
            tracker.fail(job['ordinal'])
            raise
        finally:
            if acquired:GLOBAL_TASK_SLOTS.release()

    results, errors, scheduled = _run_bounded(
        jobs, run_chunk, min(MAX_CONCURRENCY, total_chunks),
        should_stop=lambda: bool(c.ACTIVE.get(pid, {}).get('cancel')))

    promoted = 0
    for plan in plans:
        ordinals = [job['ordinal'] for job in plan['jobs']]
        if not all(ordinal in results for ordinal in ordinals):
            continue
        chunk_results = [results[ordinal] for ordinal in ordinals]
        _promote_shot(provider, pid, folder, image, resolution, plan, chunk_results)
        promoted += 1
        _progress(pid, 'MiniMax H3 对口型', 90 + 8 * promoted / len(pending),
                  f'已保存 H3 A-roll {promoted}/{len(pending)}', finish_paid_task=True)

    unstarted = total_chunks - scheduled
    if errors:
        detail = str(errors[0][1])
        suffix = f'；另有 {unstarted} 个片段尚未提交' if unstarted else ''
        raise RuntimeError(detail + '；其他已提交任务和成功结果已保留' + suffix)
    if c.ACTIVE.get(pid, {}).get('cancel') or unstarted:
        raise RuntimeError(f'已停止；已提交任务和成功结果已保留，{unstarted} 个片段尚未提交')
