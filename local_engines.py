"""Online speech and workbench-owned local media models."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
import re

from tts_common import LANGUAGES, signature

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
AZURE_PROVIDER = 'azure-v1'
SEED_PROVIDER = 'seed-audio'
INDEX_PROVIDER = 'indextts25'
AZURE_VOICES = {
    'Chinese': {
        'zh-CN-XiaoxiaoNeural': '中文女声 · 晓晓（默认）',
        'zh-CN-XiaoyiNeural': '中文女声 · 晓伊',
        'zh-CN-liaoning-XiaobeiNeural': '中文女声 · 晓北（辽宁）',
        'zh-CN-shaanxi-XiaoniNeural': '中文女声 · 晓妮（陕西）',
        'zh-CN-XiaoxiaoMultilingualNeural-V2': '中文女声 · 晓晓多语种 V2',
        'zh-CN-YunjianNeural': '中文男声 · 云健',
        'zh-CN-YunxiNeural': '中文男声 · 云希',
        'zh-CN-YunxiaNeural': '中文男声 · 云夏',
        'zh-CN-YunyangNeural': '中文男声 · 云扬',
    },
    'English': {
        'en-US-AvaNeural': '英文女声 · Ava',
        'en-US-EmmaNeural': '英文女声 · Emma',
        'en-US-JennyNeural': '英文女声 · Jenny',
        'en-US-AndrewNeural': '英文男声 · Andrew',
        'en-US-BrianNeural': '英文男声 · Brian',
        'en-US-GuyNeural': '英文男声 · Guy',
    },
}
AZURE_DEFAULT = {'Chinese': 'zh-CN-XiaoxiaoNeural', 'English': 'en-US-AvaNeural'}


def status():
    import aroll
    import core as c
    from providers.aroll import get_aroll_provider

    import voice_tts
    cfg=c.settings(True)
    azure = {'name': 'Azure TTS V1', 'ready': importlib.util.find_spec('edge_tts') is not None,
             'configured': True, 'online': True}
    seed=voice_tts.seed_status(cfg);index=voice_tts.index_status(cfg,check_online=True)
    selected=get_aroll_provider(cfg);selected_status=selected.status()
    return {
        'tts': {**azure, 'provider': AZURE_PROVIDER},
        'providers': {AZURE_PROVIDER: azure,SEED_PROVIDER:seed,INDEX_PROVIDER:index},
        'musetalk': aroll.installation_status(),
        'aroll': {'id':selected.id,'name':selected.name,'short_name':selected.short_name,**selected_status},
        'azure_voices': AZURE_VOICES,
        'languages': LANGUAGES,
    }


def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def provider_status(provider, settings=None, check_online=False):
    import core as c
    import voice_tts
    settings=settings or c.settings(True)
    if provider==AZURE_PROVIDER:
        ready=importlib.util.find_spec('edge_tts') is not None
        return {'name':'Azure TTS V1','ready':ready,'configured':True,'online':True,
                'message':'Azure TTS V1 已就绪' if ready else 'Azure TTS V1 组件待安装'}
    if provider==SEED_PROVIDER:return voice_tts.seed_status(settings)
    if provider==INDEX_PROVIDER:return voice_tts.index_status(settings,check_online=check_online)
    raise ValueError('请选择支持的配音引擎')


def test_provider_connection(provider, settings=None):
    import core as c
    import voice_tts
    settings=settings or c.settings(True)
    if provider==SEED_PROVIDER:return voice_tts.test_seed_connection(settings)
    if provider==INDEX_PROVIDER:return voice_tts.test_index_connection(settings)
    state=provider_status(provider,settings,check_online=True)
    if not state['ready']:raise ValueError(state['message'])
    return {'ok':True,'message':state['message']}


def validate_script(body, require_reference=False):
    text = body.get('text', '')
    if not isinstance(text, str) or not text.strip() or len(text) > 20000 or '\0' in text:
        raise ValueError('请输入 1–20000 字的播客原稿')
    language = body.get('language', 'Chinese')
    if language not in LANGUAGES:
        raise ValueError('配音语言无效')
    provider = str(body.get('provider') or AZURE_PROVIDER).strip().lower()
    if provider not in (AZURE_PROVIDER,SEED_PROVIDER,INDEX_PROVIDER):
        raise ValueError('请选择支持的配音引擎')
    if provider in (SEED_PROVIDER,INDEX_PROVIDER) and language!='Chinese':
        raise ValueError('豆包 SeedAudio 与 IndexTTS 2.5 当前使用中文配音')
    reference=str(body.get('reference') or '').strip().replace('\\','/')
    if reference and (not reference.startswith('assets/') or '..' in reference.split('/') or
                      not reference.lower().endswith(('.wav','.mp3','.m4a','.aac','.flac','.ogg'))):
        raise ValueError('参考声音路径无效，请重新上传')
    speaker = str(body.get('speaker') or '').strip()
    if provider==AZURE_PROVIDER and speaker not in AZURE_VOICES[language]:
        speaker = AZURE_DEFAULT[language]
    elif provider==SEED_PROVIDER:
        if speaker not in ('seed-reference','seed-natural-female','seed-natural-male'):
            speaker='seed-reference' if reference else 'seed-natural-female'
        if require_reference and speaker=='seed-reference' and not reference:
            raise ValueError('请先上传一段参考声音，再使用 SeedAudio 声纹复刻')
    elif provider==INDEX_PROVIDER:
        speaker='index-reference'
        if require_reference and not reference:
            raise ValueError('请先上传一段参考声音，再使用 IndexTTS 2.5 本地配音')
    try:
        speed = round(float(body.get('speed', 1.0)), 2)
    except (TypeError, ValueError):
        raise ValueError('配音语速无效')
    if speed < .5 or speed > 2:
        raise ValueError('配音语速需在 0.5–2.0 倍之间')
    return {'text': text.strip(), 'provider': provider, 'speaker': speaker, 'language': language,
            'speed': speed, 'reference': reference}


def project_script(project, require_reference=False):
    """Use the project's uploaded voice as the authoritative clone reference."""
    body=dict(project.get('script') or {})
    provider=str(body.get('provider') or AZURE_PROVIDER).strip().lower()
    speaker=str(body.get('speaker') or '').strip()
    if provider==INDEX_PROVIDER or (provider==SEED_PROVIDER and speaker=='seed-reference'):
        body['reference']=str(project.get('voice_reference') or body.get('reference') or '')
    return validate_script(body,require_reference=require_reference)


def needs_tts(project):
    script = project.get('script')
    if not script:
        return False
    if not project.get('audio'):
        return True
    tts = project.get('tts') or {}
    try:
        effective=project_script(project)
        compared = ('text', 'speaker', 'language') + tuple(
            key for key in ('provider', 'speed', 'reference') if key in effective)
        if tts.get('engine') and all(tts.get(key) == effective.get(key) for key in compared):
            return False
        return tts.get('signature') != signature(**effective)
    except (TypeError, ValueError):
        return True


def synthesize(pid):
    import core as c
    import voice_tts

    project = c.read_project(pid)
    script = project_script(project,require_reference=True)
    current=provider_status(script['provider'],c.settings(True),check_online=script['provider']==INDEX_PROVIDER)
    if not current['ready']:
        raise ValueError(current['message'])
    key = signature(**script)
    folder = c.project_dir(pid) / 'assets/tts' / key
    folder.mkdir(parents=True, exist_ok=True)
    if script['provider']==AZURE_PROVIDER:
        request = folder / 'request.json'
        c.atomic_json(request, {**script, 'folder': str(folder), 'ffmpeg': str(c.FFMPEG), 'timeout': 45})
        progress_file = folder / 'progress.json'
        progress_file.unlink(missing_ok=True)
        env = os.environ.copy()
        env.update(PYTHONIOENCODING='utf-8')
        c.progress(pid, '文字配音', 1, '正在启动联网 Azure TTS V1；已完成的段落会复用')
        with (folder / 'worker.log').open('wb') as log:
            proc = subprocess.Popen(
                [sys.executable, str(c.ROOT / 'azure_tts_worker.py'), str(request)],
                env=env,
                stdout=log,
                stderr=log,
                creationflags=FLAGS,
            )
            began = time.monotonic()
            try:
                while proc.poll() is None:
                    percent = 1
                    message = '正在连接 Azure TTS V1…'
                    try:
                        progress_state = json.loads(progress_file.read_text(encoding='utf-8'))
                        percent = 2 + 94 * progress_state['done'] / max(1, progress_state['total'])
                        message = progress_state['message']
                    except (OSError, ValueError, KeyError):
                        pass
                    c.progress(pid, '文字配音', percent, message)
                    if time.monotonic() - began > 6 * 3600:
                        raise RuntimeError('配音超过六小时，请缩短原稿；已完成段落保留')
                    time.sleep(.5)
                if proc.returncode:
                    detail = (folder / 'worker.log').read_text(encoding='utf-8', errors='replace')[-1400:]
                    raise RuntimeError('Azure TTS V1 联网配音失败：' + detail)
            finally:
                stop(proc)
        result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
    else:
        result=voice_tts.synthesize(pid,project,script,folder,key)
    c.progress(pid, '文字配音', 98, '正在建立音轨与原稿字幕时间')
    master = folder / 'master.wav'
    temporary = folder / 'master.tmp.wav'
    c.run([c.FFMPEG, '-y', '-v', 'error', '-i', folder / 'combined.wav', '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', temporary])
    os.replace(temporary, master)
    duration = round(c.probe(master)['duration'], 3)
    segments = c.normalize_segments(result['segments'], duration)
    waveform = c.waveform(master)
    with c.LOCK:
        c.progress(pid, '文字配音', 99, '配音完成')
        project = c.read_project(pid)
        if project.get('audio'):
            project.setdefault('audio_history', []).append({key: project.get(key) for key in ('audio', 'audio_name', 'tts', 'duration')})
        label = (AZURE_VOICES[script['language']][script['speaker']] if script['provider']==AZURE_PROVIDER else
                 {'seed-reference':'豆包 SeedAudio · 参考声音','seed-natural-female':'豆包 SeedAudio · 自然女声',
                  'seed-natural-male':'豆包 SeedAudio · 自然男声','index-reference':'IndexTTS 2.5 · 参考声音'}[script['speaker']])
        project.update(
            script=script,
            audio=master.relative_to(c.project_dir(pid)).as_posix(),
            audio_name=f'文字配音 · {label}.wav',
            duration=duration,
            segments=segments,
            candidate_segments=[],
            narrative_segments=[],
            shots=[],
            analysis=None,
            waveform=waveform,
            tts={**result, **script, 'signature': key},
            transcription={'engine': result['engine'], 'phrase_timing': 'awaiting-script-alignment', 'language': script['language']},
        )
        project['revision'] += 1
        c.save_project(project)


def install(pid):
    import core as c

    c.progress(pid, '安装本地媒体引擎', 0, '首次安装将下载独立 MuseTalk 口型模型，可在失败后继续')
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    logpath = c.DATA / 'media-engine-install.log'
    with logpath.open('wb') as log:
        proc = subprocess.Popen(
            [sys.executable, '-u', str(c.ROOT / 'engine_setup.py')],
            env=env,
            stdout=log,
            stderr=log,
            creationflags=FLAGS,
        )
        try:
            while proc.poll() is None:
                with logpath.open('rb') as tail:
                    tail.seek(max(0, logpath.stat().st_size - 2000))
                    lines = tail.read().decode('utf-8', 'replace').splitlines()
                c.progress(pid, '安装本地媒体引擎', 0, (lines[-1] if lines else '正在准备下载…')[:400])
                time.sleep(1)
            if proc.returncode:
                raise RuntimeError('安装未完成，可点击继续重试。' + logpath.read_text(encoding='utf-8', errors='replace')[-1000:])
        finally:
            if proc.poll() is None and os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, creationflags=FLAGS)
            stop(proc)


def install_wav2lip(pid):
    import core as c
    import wav2lip_setup as setup

    cfg=c.settings(True)
    if not (cfg.get('wav2lip_license_acknowledged') and
            cfg.get('wav2lip_license_reference')==setup.LICENSE_REFERENCE):
        raise ValueError('请先阅读并确认 Wav2Lip 第三方非商业使用限制')
    c.progress(pid,'安装 Wav2Lip',1,'正在准备独立 Wav2Lip 环境…')
    logdir=c.DATA/'logs';logdir.mkdir(parents=True,exist_ok=True)
    logpath=logdir/'wav2lip-install.log';env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
    with logpath.open('wb') as log:
        proc=subprocess.Popen([sys.executable,'-u',str(c.ROOT/'wav2lip_setup.py'),'--acknowledge-license'],
                              cwd=c.ROOT,env=env,stdout=log,stderr=log,creationflags=FLAGS)
        try:
            while proc.poll() is None:
                with logpath.open('rb') as tail:
                    tail.seek(max(0,logpath.stat().st_size-3000))
                    lines=tail.read().decode('utf-8','replace').splitlines()
                line=next((value for value in reversed(lines) if value.strip()),'正在准备下载…')
                match=re.match(r'\[(\d{3})\]\s*(.*)',line)
                percent=int(match.group(1)) if match else 1;message=match.group(2) if match else line
                c.progress(pid,'安装 Wav2Lip',percent,message[:400]);time.sleep(1)
            if proc.returncode:
                detail=logpath.read_text(encoding='utf-8',errors='replace')[-1800:]
                last=next((value.strip() for value in reversed(detail.splitlines()) if value.strip()),'安装失败')
                raise RuntimeError('Wav2Lip 安装未完成，可选择官方模型文件后重试。'+last[-700:])
        finally:
            if proc.poll() is None and os.name=='nt':
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=FLAGS)
            stop(proc)


def install_aroll(pid):
    import core as c
    from providers.aroll import get_aroll_provider
    provider=get_aroll_provider(c.settings(True))
    if provider.id=='musetalk':return install(pid)
    if provider.id=='wav2lip':return install_wav2lip(pid)
    raise ValueError(f'{provider.name} 不需要本地安装，请在「连接与设置」完成连接配置')
