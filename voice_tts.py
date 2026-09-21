"""SeedAudio and local IndexTTS 2.5 adapters for SceneFlow."""
from __future__ import annotations

import base64
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import requests

from atomic_files import atomic_json
from tts_common import split_script

SEED_AUDIO_URL = 'https://openspeech.bytedance.com/api/v3/tts/create'
SEED_MODEL = 'seed-audio-1.0'
INDEX_DEFAULT_URL = 'http://127.0.0.1:8189'
INDEX_REQUIRED_NODES = ('JR_IndexTTS25_Loader', 'JR_IndexTTS25_VoicePreset', 'JR_IndexTTS25_Generate')
MAX_AUDIO_BYTES = 512 * 1024 * 1024


def _base_url(value):
    value = str(value or INDEX_DEFAULT_URL).strip().rstrip('/')
    if not value.startswith(('http://', 'https://')):
        raise ValueError('IndexTTS 2.5 地址必须以 http:// 或 https:// 开头')
    return value


def seed_status(settings):
    configured = bool(str(settings.get('tts_seed_api_key') or '').strip())
    return {
        'name': '豆包 SeedAudio', 'ready': configured, 'configured': configured, 'online': True,
        'message': 'SeedAudio Key 已保存在本机' if configured else '请在连接与设置中填写 SeedAudio API Key',
    }


def index_status(settings, check_online=False):
    base = _base_url(settings.get('tts_index_url'))
    result = {'name': 'IndexTTS 2.5 本地', 'ready': True, 'configured': True, 'online': None,
              'message': f'已连接到 {base}' if not check_online else '正在检查本地工作流'}
    if not check_online:
        result['message'] = f'本地地址已配置：{base}'
        return result
    try:
        response = requests.get(base + '/object_info/JR_IndexTTS25_Generate', timeout=(2, 5))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or 'JR_IndexTTS25_Generate' not in payload:
            raise ValueError('当前 ComfyUI 没有 JR IndexTTS 2.5 节点')
        result.update(ready=True, online=True, message='IndexTTS 2.5 节点已就绪')
    except Exception as exc:
        result.update(ready=False, online=False,
                      message='本地 IndexTTS 2.5 未就绪，请确认 ComfyUI 8189 已启动且节点可用')
        result['detail'] = str(exc)[-300:]
    return result


def test_seed_connection(settings):
    status = seed_status(settings)
    if not status['ready']:
        raise ValueError(status['message'])
    return {'ok': True, 'message': 'SeedAudio Key 已配置；为避免产生费用，首次生成时再验证权限'}


def test_index_connection(settings):
    status = index_status(settings, check_online=True)
    if not status['ready']:
        raise ValueError(status['message'])
    return {'ok': True, 'message': status['message']}


def _download(response, target):
    total = 0
    temporary = target.with_suffix(target.suffix + '.part')
    try:
        with temporary.open('wb') as stream:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_AUDIO_BYTES:
                    raise RuntimeError('配音结果超过 512 MB，已停止下载')
                stream.write(chunk)
        if total <= 44:
            raise RuntimeError('配音服务返回了空音频')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _seed_chunk(settings, script, reference, text, raw, request_file):
    speaker = script['speaker']
    reference_data = base64.b64encode(reference.read_bytes()).decode('ascii') if reference else ''
    voice_line = {
        'seed-natural-female': '一位成年女性播客主持人，音色自然、清晰、稳定。',
        'seed-natural-male': '一位成年男性播客主持人，音色自然、清晰、稳定。',
    }.get(speaker, '严格沿用@音频1中的身份、年龄、性别和基础音色，不要换人。')
    prompt = '\n'.join([
        voice_line,
        '用自然、克制、清楚的普通话播客语气表达，把停顿、重音和呼吸落在语义上。',
        '只生成一个人的干净近讲人声，不要旁白标签、环境声、音效或音乐。',
        f'主持人说：“{text}”',
    ])
    audio_config = {'format': 'wav', 'sample_rate': 24000, 'speech_rate': 0,
                    'loudness_rate': 0, 'pitch_rate': 0, 'enable_subtitle': True}
    request_body = {'model': SEED_MODEL, 'text_prompt': prompt, 'audio_config': audio_config}
    if reference_data:
        request_body['references'] = [{'audio_data': reference_data}]
    atomic_json(request_file, {'model': SEED_MODEL, 'text_prompt': prompt,
                               'audio_config': audio_config, 'has_reference': bool(reference_data)})
    response = requests.post(SEED_AUDIO_URL,
                             headers={'content-type': 'application/json',
                                      'X-Api-Key': str(settings['tts_seed_api_key']).strip(),
                                      'X-Api-Request-Id': str(uuid.uuid4())},
                             json=request_body, timeout=(15, 600))
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(f'SeedAudio 返回了无法解析的内容（HTTP {response.status_code}）') from exc
    if response.status_code >= 400 or int(result.get('code', 0) or 0) != 0:
        raise RuntimeError('SeedAudio 配音失败：' + str(result.get('message') or response.reason))
    encoded = result.get('audio')
    if encoded:
        if ',' in encoded and encoded.lstrip().startswith('data:'):
            encoded = encoded.split(',', 1)[1]
        try:
            data = base64.b64decode(''.join(str(encoded).split()), validate=True)
        except Exception as exc:
            raise RuntimeError('SeedAudio 返回的音频数据无效') from exc
        if len(data) <= 44:
            raise RuntimeError('SeedAudio 返回了空音频')
        raw.write_bytes(data)
        return
    url = str(result.get('url') or '').strip()
    if not url.startswith(('http://', 'https://')):
        raise RuntimeError('SeedAudio 返回中没有可用音频')
    download = requests.get(url, stream=True, timeout=(15, 120))
    download.raise_for_status()
    _download(download, raw)


def _upload_reference(base, reference, folder, pid, key):
    manifest = folder / 'index-reference.json'
    if manifest.is_file():
        try:
            saved = json.loads(manifest.read_text(encoding='utf-8'))
            if saved.get('name'):
                return (saved.get('subfolder') + '/' if saved.get('subfolder') else '') + saved['name']
        except (OSError, ValueError):
            pass
    safe_name = f'sceneflow_{pid}_{key}.wav'
    with reference.open('rb') as stream:
        response = requests.post(base + '/upload/image', files={'image': (safe_name, stream, 'audio/wav')},
                                 data={'type': 'input', 'overwrite': 'true'}, timeout=(10, 120))
    response.raise_for_status()
    result = response.json()
    name = str(result.get('name') or safe_name)
    subfolder = str(result.get('subfolder') or '')
    atomic_json(manifest, {'name': name, 'subfolder': subfolder})
    return (subfolder + '/' if subfolder else '') + name


def build_index_prompt(text, reference_name, speaker_name, speed, seed, prefix):
    return {
        '1': {'class_type': 'JR_IndexTTS25_Loader', 'inputs': {
            'model_path_override': '', 'download_model': False, 'source_path_override': '',
            'device': 'cuda:0', 'precision': 'fp32', 'enable_qwen_emotion': True,
            'strict_environment': False,
        }},
        '2': {'class_type': 'LoadAudio', 'inputs': {'audio': reference_name}},
        '3': {'class_type': 'JR_IndexTTS25_VoicePreset', 'inputs': {
            'reference_audio': ['2', 0], 'speaker_name': speaker_name, 'overwrite_existing': True,
        }},
        '4': {'class_type': 'JR_IndexTTS25_Generate', 'inputs': {
            'model': ['1', 0], 'voice': ['3', 0], 'text': text, 'language': 'ZH',
            'duration_factor': max(.5, min(2.0, 1 / speed)), 'text_normalization': True,
            'interval_silence_ms': 200, 'seed': int(seed) % 2_147_483_648,
            'unload_model_after': False, 'do_sample': True, 'temperature': .72,
            'top_p': .86, 'top_k': 25, 'num_beams': 1, 'repetition_penalty': 8,
            'length_penalty': .4, 'max_mel_tokens': 1815, 'max_text_tokens_per_segment': 80,
        }},
        '7': {'class_type': 'SaveAudio', 'inputs': {'audio': ['4', 0], 'filename_prefix': prefix}},
    }


def _history_audio(record):
    if record.get('status', {}).get('status_str') == 'error':
        raise RuntimeError('IndexTTS 2.5 本地生成失败，请查看 ComfyUI 控制台')
    for output in (record.get('outputs') or {}).values():
        items = output.get('audio') or output.get('audios') or []
        if items:
            return items[-1]
    return None


def _index_chunk(c, pid, base, graph, folder, ordinal, raw):
    task_file = folder / f'chunk-{ordinal:03d}.task.json'
    prompt_id = ''
    resubmitted = False
    if task_file.is_file():
        try:
            prompt_id = str(json.loads(task_file.read_text(encoding='utf-8')).get('prompt_id') or '')
        except (OSError, ValueError):
            pass
    while True:
        if not prompt_id:
            response = requests.post(base + '/prompt', json={
                'prompt': graph, 'client_id': f'sceneflow-{pid}-{uuid.uuid4().hex[:10]}'}, timeout=(10, 60))
            response.raise_for_status()
            result = response.json()
            prompt_id = str(result.get('prompt_id') or '')
            if not prompt_id:
                raise RuntimeError('IndexTTS 2.5 提交失败：ComfyUI 未返回任务号')
            atomic_json(task_file, {'prompt_id': prompt_id})
        began = time.monotonic()
        missing_polls = 0
        while True:
            if c.ACTIVE.get(pid, {}).get('cancel'):
                try:
                    requests.post(base + '/queue', json={'delete': [prompt_id]}, timeout=(5, 10))
                    requests.post(base + '/interrupt', json={'prompt_id': prompt_id}, timeout=(5, 10))
                except requests.RequestException:
                    pass
                task_file.unlink(missing_ok=True)
                raise RuntimeError('已停止')
            c.progress(pid, '文字配音', 3, f'IndexTTS 2.5 正在生成第 {ordinal} 段…')
            response = requests.get(base + '/history/' + prompt_id, timeout=(5, 30))
            response.raise_for_status()
            history = response.json()
            record = history.get(prompt_id)
            if record:
                audio = _history_audio(record)
                if audio:
                    download = requests.get(base + '/view', params={
                        'filename': audio['filename'], 'subfolder': audio.get('subfolder', ''),
                        'type': audio.get('type', 'output')}, stream=True, timeout=(10, 120))
                    download.raise_for_status()
                    _download(download, raw)
                    return
            queue = requests.get(base + '/queue', timeout=(5, 30))
            queue.raise_for_status()
            queued = queue.json()
            present = any(item[1] == prompt_id for name in ('queue_running', 'queue_pending')
                          for item in queued.get(name, []))
            missing_polls = missing_polls + 1 if not record and not present else 0
            if missing_polls >= 3:
                task_file.unlink(missing_ok=True)
                if resubmitted:
                    raise RuntimeError('IndexTTS 2.5 任务连续两次从 ComfyUI 队列和历史中消失')
                prompt_id = ''
                resubmitted = True
                break
            if time.monotonic() - began > 2 * 3600:
                raise RuntimeError(f'IndexTTS 2.5 等待超时，任务号 {prompt_id} 已保留，可直接继续生成')
            time.sleep(1)


def _normalize(c, source, target, speed=1.0):
    command = [c.FFMPEG, '-y', '-v', 'error', '-i', source, '-vn']
    if abs(speed - 1.0) > .001:
        command += ['-af', f'atempo={speed:.3f}']
    command += ['-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', target]
    c.run(command, timeout=1800)


def _combine(c, paths, target):
    if len(paths) == 1:
        shutil.copy2(paths[0], target)
        return
    manifest = target.with_suffix('.concat.txt')
    manifest.write_text(''.join(f"file '{path.resolve().as_posix()}'\n" for path in paths), encoding='utf-8')
    c.run([c.FFMPEG, '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', manifest,
           '-c:a', 'pcm_s16le', target], timeout=1800)


def synthesize(pid, project, script, folder, key):
    import core as c

    settings = c.settings(True)
    provider = script['provider']
    reference = c.asset_path(pid, script['reference']) if script.get('reference') else None
    chunks = split_script(script['text'], limit=700)
    normalized = []
    if provider == 'seed-audio':
        if not seed_status(settings)['ready']:
            raise ValueError(seed_status(settings)['message'])
        engine = '豆包 SeedAudio'
        for index, text in enumerate(chunks, 1):
            raw = folder / f'chunk-{index:03d}.seed-audio'
            wav = folder / f'chunk-{index:03d}.wav'
            if not wav.is_file():
                c.progress(pid, '文字配音', 2 + 92 * (index - 1) / len(chunks),
                           f'豆包 SeedAudio 正在生成第 {index}/{len(chunks)} 段…')
                if not raw.is_file():
                    _seed_chunk(settings, script, reference, text, raw,
                                folder / f'chunk-{index:03d}.request.json')
                _normalize(c, raw, wav, script['speed'])
            normalized.append(wav)
    elif provider == 'indextts25':
        status = index_status(settings, check_online=True)
        if not status['ready']:
            raise ValueError(status['message'])
        engine = 'IndexTTS 2.5 本地'
        base = _base_url(settings.get('tts_index_url'))
        reference_name = _upload_reference(base, reference, folder, pid, key)
        seed = int(key[:8], 16)
        speaker_name = ('SceneFlow_' + pid + '_' + key[:8])[:80]
        for index, text in enumerate(chunks, 1):
            raw = folder / f'chunk-{index:03d}.index-audio'
            wav = folder / f'chunk-{index:03d}.wav'
            if not wav.is_file():
                graph = build_index_prompt(text, reference_name, speaker_name, script['speed'],
                                           seed + index - 1, f'SceneFlow/{pid}/{key}/chunk-{index:03d}')
                atomic_json(folder / f'chunk-{index:03d}.workflow.json', graph)
                if not raw.is_file():
                    _index_chunk(c, pid, base, graph, folder, index, raw)
                _normalize(c, raw, wav)
            normalized.append(wav)
    else:
        raise ValueError('不支持的配音引擎')
    _combine(c, normalized, folder / 'combined.wav')
    duration = round(c.probe(folder / 'combined.wav')['duration'], 3)
    result = {'engine': engine, 'provider': provider, 'speaker': script['speaker'],
              'language': script['language'], 'speed': script['speed'],
              'reference': script.get('reference', ''),
              'segments': [{'start': 0, 'end': duration, 'text': script['text']}],
              'chunk_count': len(chunks)}
    atomic_json(folder / 'result.json', result)
    return result
