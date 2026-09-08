from __future__ import annotations

import json
import math
import os
import subprocess
import time
import uuid
from pathlib import Path
from threading import RLock

from .base import ArollProvider

_PROCESSES: dict[str, subprocess.Popen] = {}
_PROCESS_LOCK = RLock()


class Wav2LipProvider(ArollProvider):
    id = 'wav2lip'
    name = 'Wav2Lip'
    short_name = 'Wav2Lip · 轻量'
    runtime = 'local'

    @property
    def version(self):
        import wav2lip_setup as setup
        return setup.PROVIDER_VERSION

    def license_acknowledged(self):
        import wav2lip_setup as setup
        return (self.settings.get('wav2lip_license_acknowledged') is True and
                self.settings.get('wav2lip_license_reference') == setup.LICENSE_REFERENCE)

    def status(self, check_online=False):
        import wav2lip_setup as setup
        value = setup.installation_status()
        acknowledged = self.license_acknowledged()
        if value.get('ready') and not acknowledged:
            value = {**value, 'ready': False, 'message': '请重新确认 Wav2Lip 第三方使用限制'}
        return {**value, 'license_acknowledged': acknowledged,
                'license_reference': setup.LICENSE_REFERENCE,
                'license_notice': '仅限个人 / 研究 / 非商业用途',
                'checkpoint_page': setup.CHECKPOINT_PAGE}

    def validate_config(self):
        return True

    def cache_identity(self):
        import wav2lip_setup as setup
        return {
            'provider': self.id, 'provider_version': setup.PROVIDER_VERSION,
            'model': 'Wav2Lip-SD-GAN', 'checkpoint': setup.CHECKPOINT_SHA256,
            'adapter': setup.ADAPTER_VERSION, 'workflow_hash': None,
        }

    def generate(self, pid, shot_id=None):
        if not self.license_acknowledged():
            raise ValueError('请先阅读并确认 Wav2Lip 第三方非商业使用限制')
        if not self.status().get('ready'):
            raise ValueError('Wav2Lip 尚未安装，请在「连接与设置」安装轻量口型组件')
        return generate(pid, shot_id, self.cache_identity())

    def cancel(self, pid):
        cancel(pid)


def _stop_process(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def cancel(pid):
    with _PROCESS_LOCK:
        proc = _PROCESSES.get(pid)
    if proc is not None:
        _stop_process(proc)


def prepare_video(source: Path, target: Path, start: float, duration: float):
    """Make a 720p, 25 fps, silent forward loop at the podcast time."""
    import aroll
    import core as c

    frames = math.ceil(duration * aroll.FPS) + 2
    if aroll.valid_chunk(target, frames):
        return
    temp = target.with_suffix('.part.mp4')
    loop_duration = c.probe(source)['duration']
    phase = (round(start * aroll.FPS) % max(1, round(loop_duration * aroll.FPS))) / aroll.FPS
    filters = ('fps=25,'
               f'trim=start_frame={round(phase * aroll.FPS)},setpts=PTS-STARTPTS,'
               'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,'
               'pad=1280:720:(ow-iw)/2:(oh-ih)/2:black,setsar=1')
    c.run([c.FFMPEG, '-y', '-v', 'error', '-stream_loop', '-1', '-i', source, '-an',
           '-vf', filters, '-frames:v', str(frames), '-c:v', 'libx264', '-preset', 'veryfast',
           '-crf', '18', '-pix_fmt', 'yuv420p', '-threads', '4', '-movflags', '+faststart', temp])
    if not aroll.valid_chunk(temp, frames):
        raise RuntimeError('Wav2Lip 循环视频片段帧数校验失败')
    temp.replace(target)


def _run_worker_once(pid: str, request: dict, progress_file: Path):
    import core as c
    import wav2lip_setup as setup

    request_file = progress_file.with_name('request.json')
    c.atomic_json(request_file, request)
    logpath = progress_file.with_name('worker.log')
    progress_file.unlink(missing_ok=True)
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    with logpath.open('wb') as log:
        proc = subprocess.Popen([str(setup.runtime_python()), str(c.ROOT / 'wav2lip_worker.py'),
                                 str(request_file)], cwd=c.ROOT, env=env, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        with _PROCESS_LOCK:
            _PROCESSES[pid] = proc
        began = time.monotonic()
        try:
            while proc.poll() is None:
                if c.ACTIVE.get(pid, {}).get('cancel'):
                    _stop_process(proc)
                    raise RuntimeError('已停止；完成的 Wav2Lip 口型缓存会在下次继续使用')
                message, percent = '正在加载 Wav2Lip 模型…', 2
                try:
                    state = json.loads(progress_file.read_text(encoding='utf-8'))
                    message = state.get('message', message)
                    task = state.get('task', 0)
                    tasks = max(1, state.get('tasks', len(request['tasks'])))
                    batch = state.get('batch', 0)
                    batches = max(1, state.get('batches', 1))
                    percent = 3 + 92 * ((task - 1 + batch / batches) / tasks) if task else 2
                except (OSError, ValueError, KeyError):
                    pass
                c.progress(pid, 'Wav2Lip 对口型', percent, message)
                if time.monotonic() - began > 6 * 3600:
                    raise RuntimeError('Wav2Lip 推理超过六小时；缓存已保留，可重试')
                time.sleep(.5)
            if proc.returncode:
                return logpath.read_text(encoding='utf-8', errors='replace')[-2400:]
        finally:
            _stop_process(proc)
            with _PROCESS_LOCK:
                if _PROCESSES.get(pid) is proc:
                    _PROCESSES.pop(pid, None)


def run_worker(pid: str, request: dict, progress_file: Path):
    import core as c

    batch = min(int(task.get('batch_size', 64)) for task in request['tasks'])
    while True:
        detail = _run_worker_once(pid, request, progress_file)
        if detail is None:
            return
        lower = detail.lower()
        if 'out of memory' not in lower and 'cudnn_status_alloc_failed' not in lower:
            last = next((line.strip() for line in reversed(detail.splitlines()) if line.strip()), '')
            raise RuntimeError('Wav2Lip 推理失败：' + last[-600:])
        if batch <= 1:
            raise RuntimeError('Wav2Lip 显存不足。请降低人物素材分辨率，或改用 MuseTalk 低显存档 / 在线 A-roll')
        batch = max(1, batch // 2)
        for task in request['tasks']:
            task['batch_size'] = batch
        c.progress(pid, 'Wav2Lip 对口型', 3, f'显存不足，已降到每批 {batch} 帧重试')


def generate(pid: str, shot_id=None, provider_identity=None):
    import aroll
    import core as c
    import wav2lip_setup as setup
    from PIL import Image, ImageOps

    p = c.read_project(pid)
    runs = aroll.contiguous_runs(p['shots'])
    if shot_id and not any(any(shot['id'] == shot_id for shot in run) for run in runs):
        raise ValueError('未找到选中的 A-roll 镜头')
    pending = [run for run in runs if (
        (not shot_id and any(not aroll.is_ready(p, shot, provider_identity) for shot in run)) or
        (shot_id and any(shot['id'] == shot_id for shot in run))
    )]
    if not pending:
        return
    c.validate_timeline(p['shots'], p['duration'])
    folder = c.project_dir(pid)
    is_video = aroll.video_source(p)
    prepared = []
    for run in pending:
        stable = aroll.run_signature(p, run, provider_identity)
        suffix = '-' + uuid.uuid4().hex[:6] if shot_id else ''
        key = stable + suffix
        cache = folder / 'aroll-cache' / ('wav2lip-' + key)
        cache.mkdir(parents=True, exist_ok=True)
        context_start = max(0, float(run[0]['start']) - aroll.CONTEXT)
        context_end = min(p['duration'], float(run[-1]['end']) + aroll.CONTEXT)
        duration = context_end - context_start
        audio = cache / 'audio.wav'
        if not audio.exists():
            c.run([c.FFMPEG, '-y', '-v', 'error', '-ss', str(context_start), '-i',
                   c.asset_path(pid, p['audio']), '-t', str(duration), '-vn', '-ac', '1', '-ar',
                   '16000', '-c:a', 'pcm_s16le', audio])
        if is_video:
            source = cache / 'host.mp4'
            prepare_video(c.host_media(p), source, context_start, duration)
        else:
            source = cache / 'host.jpg'
            if not source.exists():
                with Image.open(c.host_image(p)) as image:
                    ImageOps.fit(image.convert('RGB'), (1280, 720),
                                 method=Image.Resampling.LANCZOS).save(source, quality=95)
        items = []
        for shot in run:
            signature = aroll.signature(p, shot, provider_identity)
            start_frame = round((float(shot['start']) - context_start) * aroll.FPS)
            end_frame = round((float(shot['end']) - context_start) * aroll.FPS)
            items.append({'shot': shot, 'signature': signature, 'frames': end_frame - start_frame,
                          'start_frame': start_frame})
        prepared.append({'run': run, 'cache': cache, 'raw': cache / 'raw.mp4',
                         'source': source, 'audio': audio, 'duration': duration,
                         'frames': max(1, round(duration * aroll.FPS)), 'items': items,
                         'asset_key': key})
    tasks = [{
        'repo': str(setup.source_root()), 'video': str(item['source']),
        'audio': str(item['audio']), 'output': str(item['raw']), 'ffmpeg': str(c.FFMPEG),
        'frames': item['frames'], 'batch_size': 64, 'face_batch_size': 16,
    } for item in prepared if not aroll.valid_chunk(item['raw'], item['frames'])]
    if tasks:
        runroot = folder / 'aroll-cache' / ('wav2lip-run-' + uuid.uuid4().hex[:10])
        runroot.mkdir(parents=True, exist_ok=True)
        progress = runroot / 'progress.json'
        run_worker(pid, {'checkpoint': str(setup.checkpoint_path()), 'progress': str(progress),
                         'tasks': tasks}, progress)
    total = sum(len(item['items']) for item in prepared)
    written = 0
    for run_item in prepared:
        run_start = run_item['items'][0]['start_frame']
        run_end = run_item['items'][-1]['start_frame'] + run_item['items'][-1]['frames']
        run_frames = run_end - run_start
        finished = run_item['cache'] / 'finished-run.mp4'
        if not aroll.valid_chunk(finished, run_frames):
            aroll.trim_chunk_frames(run_item['raw'], finished, run_start, run_frames)
        asset = folder / 'assets' / f'aroll-run-wav2lip-{run_item["asset_key"]}.mp4'
        temp = asset.with_suffix('.part.mp4')
        c.run([c.FFMPEG, '-y', '-v', 'error', '-i', finished, '-an', '-c:v', 'copy',
               '-movflags', '+faststart', temp])
        info = c.probe(temp)
        if any(stream['codec_type'] == 'audio' for stream in info['streams']):
            raise RuntimeError('Wav2Lip A-roll 不应包含音轨')
        expected = run_frames / aroll.FPS
        if abs(info['duration'] - expected) > .04:
            raise RuntimeError('Wav2Lip 连续 A-roll 时长校验失败')
        temp.replace(asset)
        for item in run_item['items']:
            with c.LOCK:
                current = c.read_project(pid)
                target = next(shot for shot in current['shots'] if shot['id'] == item['shot']['id'])
                relative = asset.relative_to(folder).as_posix()
                if target.get('aroll_asset') and target['aroll_asset'] != relative:
                    target.setdefault('aroll_history', []).append({
                        'asset': target['aroll_asset'], 'signature': target.get('aroll_signature')})
                target.update(
                    aroll_asset=relative, aroll_signature=item['signature'], aroll_status='ready',
                    aroll_error=None,
                    aroll_provenance={
                        'provider': 'wav2lip', 'engine': 'Wav2Lip', 'runtime': 'local',
                        'provider_version': setup.PROVIDER_VERSION, 'model': 'Wav2Lip-SD-GAN',
                        'checkpoint_sha256': setup.CHECKPOINT_SHA256,
                        'adapter': setup.ADAPTER_VERSION,
                        'license_scope': 'third-party-noncommercial',
                        'source': c.host_media(p).relative_to(folder).as_posix(),
                        'source_kind': 'video' if is_video else 'image',
                        'loop_mode': 'forward' if is_video else None, 'fps': aroll.FPS,
                        'duration': item['frames'] / aroll.FPS,
                        'continuous_asset_duration': info['duration'],
                        'audio_start': item['shot']['start'], 'audio_end': item['shot']['end'],
                        'continuous_run_start': run_item['run'][0]['start'],
                        'continuous_run_end': run_item['run'][-1]['end'],
                    },
                    aroll_media_start=(item['start_frame'] - run_start) / aroll.FPS,
                )
                current['revision'] += 1
                c.save_project(current)
            written += 1
            c.progress(pid, 'Wav2Lip 对口型', 96 + 3 * written / total,
                       f'已写入口型 {written}/{total}')
