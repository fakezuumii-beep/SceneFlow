"""LatentSync 1.6 through the user's local ComfyUI server."""
from __future__ import annotations

import json
import math
import time
import uuid

import requests

from .base import ArollProvider


FPS = 25
CONTEXT = .2
TAIL = .16
SEED = 1247
DEFAULT_LIPS_EXPRESSION = 1.5
DEFAULT_INFERENCE_STEPS = 20
OUTPUT_NODE = '4'
WORKFLOW_VERSION = 'latentsync16-comfyui-2080ti-v2'


class LatentSyncProvider(ArollProvider):
    id = 'latentsync'
    name = 'LatentSync 1.6'
    short_name = 'LatentSync 1.6 · 高质量'
    runtime = 'comfyui'
    version = 'latentsync16-provider-v1'

    def tuning(self):
        try:
            lips_expression = round(float(
                self.settings.get('aroll_latentsync_lips_expression', DEFAULT_LIPS_EXPRESSION)
            ), 1)
            inference_steps = int(
                self.settings.get('aroll_latentsync_inference_steps', DEFAULT_INFERENCE_STEPS)
            )
        except (TypeError, ValueError):
            raise ValueError('LatentSync 嘴型参数无效') from None
        if not 1.0 <= lips_expression <= 3.0:
            raise ValueError('LatentSync 嘴型表现需在 1.0 到 3.0 之间')
        if not 1 <= inference_steps <= 100:
            raise ValueError('LatentSync 生成质量需在 1 到 100 步之间')
        return lips_expression, inference_steps

    def validate_config(self):
        url = str(self.settings.get('aroll_latentsync_url') or '').strip()
        if not url.startswith(('http://', 'https://')):
            raise ValueError('请填写有效的 LatentSync ComfyUI 地址')
        self.tuning()
        return True

    def request(self, method, path, **kwargs):
        self.validate_config()
        url = str(self.settings['aroll_latentsync_url']).rstrip('/') + path
        try:
            result = requests.request(method, url, timeout=(5, 30), **kwargs)
            result.raise_for_status()
            return result
        except requests.RequestException as exc:
            detail = exc.response.text[:1200] if exc.response is not None else '请确认 8189 的 ComfyUI 已启动'
            raise ValueError('LatentSync ComfyUI 请求失败：' + detail) from exc

    def status(self, check_online=False):
        try:
            self.validate_config()
            lips_expression, inference_steps = self.tuning()
            if check_online:
                self.test_connection()
        except (ValueError, OSError) as exc:
            return {'ready': False, 'installed': False, 'message': str(exc)}
        return {
            'ready': True, 'installed': True, 'configured': True,
            'message': f'本地 ComfyUI · 25fps · 嘴型 {lips_expression:g} · {inference_steps} 步',
        }

    def test_connection(self):
        stats = self.request('GET', '/system_stats').json()
        schema = self.request('GET', '/object_info').json()
        missing = [name for name in ('VHS_LoadVideo', 'LoadAudio', 'LatentSyncNode', 'VHS_VideoCombine')
                   if name not in schema]
        if missing:
            raise ValueError('ComfyUI 缺少 LatentSync 节点：' + ', '.join(missing))
        required = schema['LatentSyncNode'].get('input', {}).get('required', {})
        if not all(name in required for name in ('images', 'audio', 'seed', 'lips_expression', 'inference_steps')):
            raise ValueError('LatentSync 节点版本不兼容，请使用已验证的 1.6 Wrapper')
        devices = stats.get('devices') or []
        gpu = str(devices[0].get('name') or '') if devices else ''
        return {'ok': True, 'message': 'LatentSync 1.6 节点与本地 GPU 已验证' + (f' · {gpu}' if gpu else '')}

    def cache_identity(self):
        lips_expression, inference_steps = self.tuning()
        return {
            'provider': self.id, 'provider_version': self.version, 'model': 'LatentSync 1.6',
            'workflow_hash': WORKFLOW_VERSION, 'endpoint': self.settings.get('aroll_latentsync_url'),
            'seed': SEED, 'lips_expression': lips_expression, 'inference_steps': inference_steps,
        }

    def upload(self, path):
        with path.open('rb') as stream:
            value = self.request(
                'POST', '/upload/image',
                files={'image': (path.name, stream)},
                data={'type': 'input', 'overwrite': 'false'},
            ).json()
        return '/'.join(x for x in (value.get('subfolder'), value['name']) if x)

    def build_prompt(self, video, audio, prefix):
        lips_expression, inference_steps = self.tuning()
        return {
            '1': {'class_type': 'VHS_LoadVideo', 'inputs': {
                'video': video, 'force_rate': FPS, 'custom_width': 0, 'custom_height': 0,
                'frame_load_cap': 0, 'skip_first_frames': 0, 'select_every_nth': 1, 'format': 'None',
            }},
            '2': {'class_type': 'LoadAudio', 'inputs': {'audio': audio}},
            '3': {'class_type': 'LatentSyncNode', 'inputs': {
                'images': ['1', 0], 'audio': ['2', 0], 'seed': SEED,
                'lips_expression': lips_expression, 'inference_steps': inference_steps,
            }},
            OUTPUT_NODE: {'class_type': 'VHS_VideoCombine', 'inputs': {
                'images': ['3', 0], 'audio': ['3', 1], 'frame_rate': FPS, 'loop_count': 0,
                'filename_prefix': prefix, 'format': 'video/h264-mp4', 'pingpong': False,
                'save_output': True, 'pix_fmt': 'yuv420p', 'crf': 18,
                'save_metadata': False, 'trim_to_audio': True,
            }},
        }

    def collect(self, pid, cache, prompt):
        import core as c

        lips_expression, inference_steps = self.tuning()
        raw = cache / 'raw.mp4'
        jobfile = cache / 'comfy-job.json'
        if jobfile.is_file():
            job = json.loads(jobfile.read_text(encoding='utf-8'))
        else:
            c.atomic_json(jobfile, {'prompt_id': None, 'state': 'submitting'})
            result = self.request('POST', '/prompt', json={'prompt': prompt, 'client_id': 'sceneflow-' + pid}).json()
            if result.get('node_errors'):
                raise ValueError('LatentSync 工作流校验失败：' + str(result['node_errors']))
            job = {'prompt_id': result['prompt_id']}
            c.atomic_json(jobfile, job)
        prompt_id = job.get('prompt_id')
        if not prompt_id:
            raise ValueError('上次提交结果不明确，请先检查 ComfyUI 队列，避免重复提交')
        began = time.monotonic()
        while True:
            if c.ACTIVE.get(pid, {}).get('cancel'):
                self.request('POST', '/queue', json={'delete': [prompt_id]})
                raise RuntimeError('工作台已停止；ComfyUI 已完成的结果会保留供下次继续取回')
            history = self.request('GET', '/history/' + prompt_id).json().get(prompt_id)
            if history:
                if history.get('status', {}).get('status_str') == 'error':
                    jobfile.unlink(missing_ok=True)
                    detail = str(history.get('status', {}).get('messages', []))[-1500:]
                    raise RuntimeError('LatentSync 推理失败：' + detail)
                output = history.get('outputs', {}).get(OUTPUT_NODE, {})
                videos = [item for group in ('gifs', 'videos', 'images')
                          for item in output.get(group, [])
                          if item.get('filename', '').lower().endswith('.mp4')]
                if videos:
                    item = videos[-1]
                    temporary = raw.with_suffix('.download.mp4')
                    params = {key: item.get(key, '') for key in ('filename', 'subfolder', 'type')}
                    with self.request('GET', '/view', params=params, stream=True) as response, temporary.open('wb') as stream:
                        for chunk in response.iter_content(1024 * 1024):
                            stream.write(chunk)
                    c.probe(temporary)
                    c.run([c.FFMPEG, '-v', 'error', '-i', temporary, '-map', '0:v:0', '-f', 'null', '-'], timeout=600)
                    temporary.replace(raw)
                    c.atomic_json(cache / 'comfy-history.json', history)
                    return raw
                if history.get('status', {}).get('completed'):
                    raise RuntimeError('LatentSync 输出节点没有返回 MP4')
            queue = self.request('GET', '/queue').json()
            active = any(item[1] == prompt_id for key in ('queue_running', 'queue_pending')
                         for item in queue.get(key, []))
            if not history and not active:
                jobfile.unlink(missing_ok=True)
                raise RuntimeError('LatentSync 任务已不在队列或历史中，请重试')
            elapsed = int(time.monotonic() - began)
            c.progress(
                pid, 'LatentSync 生成', 10,
                f'嘴型 {lips_expression:g} · {inference_steps} 步推理中 · '
                f'{elapsed // 60} 分 {elapsed % 60} 秒',
            )
            if elapsed > 12 * 3600:
                raise RuntimeError('等待 LatentSync 超时；任务编号已保存，可继续取回结果')
            time.sleep(2)

    def generate(self, pid, shot_id=None):
        import aroll
        import core as c

        project = c.read_project(pid)
        identity = self.cache_identity()
        runs = aroll.contiguous_runs(project['shots'])
        if shot_id and not any(shot['id'] == shot_id for run in runs for shot in run):
            raise ValueError('未找到 A-roll 镜头')
        pending = [run for run in runs
                   if (any(shot['id'] == shot_id for shot in run) if shot_id
                       else any(not self.is_ready(project, shot) for shot in run))]
        if not pending:
            return
        self.test_connection()
        c.validate_timeline(project['shots'], project['duration'])
        folder = c.project_dir(pid)
        is_video = aroll.video_source(project)
        for index, run in enumerate(pending):
            if c.ACTIVE.get(pid, {}).get('cancel'):
                raise RuntimeError('已停止')
            stable = aroll.run_signature(project, run, identity)
            suffix = '-' + uuid.uuid4().hex[:8] if shot_id else ''
            key = stable + suffix
            cache = folder / 'aroll-cache' / ('latentsync-' + key)
            cache.mkdir(parents=True, exist_ok=True)
            start = max(0, float(run[0]['start']) - CONTEXT)
            end = min(project['duration'], float(run[-1]['end']) + CONTEXT)
            duration = end - start
            audio = cache / ('audio-' + key + '.wav')
            source = cache / ('host-' + key + '.mp4')
            if not audio.is_file():
                c.run([
                    c.FFMPEG, '-y', '-v', 'error', '-ss', str(start),
                    '-i', c.asset_path(pid, project['audio']), '-af', f'apad=pad_dur={TAIL}',
                    '-t', str(duration + TAIL), '-vn', '-ac', '1', '-ar', '16000',
                    '-c:a', 'pcm_s16le', audio,
                ])
            frames = math.ceil((duration + TAIL) * FPS) + 2
            if is_video:
                aroll.prepare_video_chunk(c.host_media(project), source, start, duration + TAIL)
            elif not aroll.valid_chunk(source, frames):
                temporary = source.with_suffix('.part.mp4')
                c.run([
                    c.FFMPEG, '-y', '-v', 'error', '-loop', '1', '-i', c.host_image(project),
                    '-an', '-vf', f'scale=trunc(iw/2)*2:trunc(ih/2)*2,fps={FPS}',
                    '-frames:v', str(frames), '-c:v', 'libx264', '-preset', 'veryfast',
                    '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', temporary,
                ])
                if not aroll.valid_chunk(temporary, frames):
                    raise RuntimeError('LatentSync 主持人源视频帧数校验失败')
                temporary.replace(source)
            raw = cache / 'raw.mp4'
            if not raw.is_file():
                promptfile = cache / 'prompt.json'
                if promptfile.is_file():
                    prompt = json.loads(promptfile.read_text(encoding='utf-8'))
                else:
                    prompt = self.build_prompt(
                        self.upload(source), self.upload(audio), 'SceneFlow/' + pid + '/' + key,
                    )
                    c.atomic_json(promptfile, prompt)
                raw = self.collect(pid, cache, prompt)
            video = next(stream for stream in c.probe(raw)['streams'] if stream['codec_type'] == 'video')
            rate = video.get('avg_frame_rate', '0/1').split('/')
            if abs(float(rate[0]) / float(rate[1]) - FPS) > .01:
                raise RuntimeError('LatentSync 输出帧率不是 25fps')
            first = round((float(run[0]['start']) - start) * FPS)
            last = round((float(run[-1]['end']) - start) * FPS)
            if int(video.get('nb_frames', 0)) < last:
                raise RuntimeError('LatentSync 输出短于连续 A-roll；原始结果已保留，不会冻结尾帧补齐')
            run_frames = last - first
            asset = folder / 'assets' / ('aroll-run-latentsync-' + key + '.mp4')
            temporary = asset.with_suffix('.part.mp4')
            c.run([
                c.FFMPEG, '-y', '-v', 'error', '-i', raw, '-an',
                '-vf', f'trim=start_frame={first}:end_frame={last},setpts=PTS-STARTPTS',
                '-frames:v', str(run_frames), '-c:v', 'libx264', '-crf', '16',
                '-preset', 'medium', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', temporary,
            ])
            if not aroll.valid_chunk(temporary, run_frames):
                raise RuntimeError('LatentSync 连续 A-roll 帧数校验失败')
            temporary.replace(asset)
            with c.LOCK:
                current = c.read_project(pid)
                for shot in run:
                    target = next(item for item in current['shots'] if item['id'] == shot['id'])
                    if self.signature(current, target) != self.signature(project, shot):
                        raise RuntimeError('生成期间输入已变化，LatentSync 结果已保留在缓存')
                    relative = asset.relative_to(folder).as_posix()
                    if target.get('aroll_asset') and target['aroll_asset'] != relative:
                        target.setdefault('aroll_history', []).append({
                            'asset': target['aroll_asset'], 'signature': target.get('aroll_signature'),
                        })
                    target.update(
                        aroll_asset=relative, aroll_signature=self.signature(project, shot),
                        aroll_status='ready', aroll_error=None,
                        aroll_media_start=(round((shot['start'] - start) * FPS) - first) / FPS,
                        aroll_provenance={
                            **identity, 'engine': self.name, 'runtime': self.runtime, 'fps': FPS,
                            'width': video['width'], 'height': video['height'],
                            'source': c.host_media(project).relative_to(folder).as_posix(),
                            'source_kind': 'video' if is_video else 'image',
                            'loop_mode': 'forward' if is_video else None,
                            'audio_start': shot['start'], 'audio_end': shot['end'],
                            'continuous_run_start': run[0]['start'], 'continuous_run_end': run[-1]['end'],
                        },
                    )
                current['revision'] += 1
                c.save_project(current)
            c.progress(
                pid, 'LatentSync 生成', 99 * (index + 1) / len(pending),
                f'已完成连续人物片段 {index + 1}/{len(pending)}',
            )
