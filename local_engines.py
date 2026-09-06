"""Workbench-owned local media models. Planning always uses the configured API."""
from __future__ import annotations
import importlib.util, json, os, subprocess, sys, time
from pathlib import Path
from engine_setup import ENGINES, KOKORO_REPO, KOKORO_REV
from tts_worker import SPEAKERS, LANGUAGES, DEFAULT_SPEAKER, LEGACY_SPEAKERS, signature

FLAGS=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
AZURE_PROVIDER='azure-v1';KOKORO_PROVIDER='kokoro'
AZURE_VOICES={
    'Chinese':{
        'zh-CN-XiaoxiaoNeural':'中文女声 · 晓晓（默认）',
        'zh-CN-XiaoyiNeural':'中文女声 · 晓伊',
        'zh-CN-liaoning-XiaobeiNeural':'中文女声 · 晓北（辽宁）',
        'zh-CN-shaanxi-XiaoniNeural':'中文女声 · 晓妮（陕西）',
        'zh-CN-XiaoxiaoMultilingualNeural-V2':'中文女声 · 晓晓多语种 V2',
        'zh-CN-YunjianNeural':'中文男声 · 云健',
        'zh-CN-YunxiNeural':'中文男声 · 云希',
        'zh-CN-YunxiaNeural':'中文男声 · 云夏',
        'zh-CN-YunyangNeural':'中文男声 · 云扬',
    },
    'English':{
        'en-US-AvaNeural':'英文女声 · Ava',
        'en-US-EmmaNeural':'英文女声 · Emma',
        'en-US-JennyNeural':'英文女声 · Jenny',
        'en-US-AndrewNeural':'英文男声 · Andrew',
        'en-US-BrianNeural':'英文男声 · Brian',
        'en-US-GuyNeural':'英文男声 · Guy',
    },
}
AZURE_DEFAULT={'Chinese':'zh-CN-XiaoxiaoNeural','English':'en-US-AvaNeural'}
AZURE_LEGACY={
    'Serena':'zh-CN-XiaoxiaoNeural','Vivian':'zh-CN-XiaoyiNeural','Uncle_Fu':'zh-CN-YunyangNeural',
    'Dylan':'zh-CN-YunjianNeural','Eric':'zh-CN-YunxiNeural','Ryan':'en-US-GuyNeural','Aiden':'en-US-AndrewNeural',
    'zf_xiaoni':'zh-CN-XiaoxiaoNeural','zf_xiaobei':'zh-CN-liaoning-XiaobeiNeural',
    'zf_xiaoxiao':'zh-CN-XiaoxiaoNeural','zf_xiaoyi':'zh-CN-XiaoyiNeural',
    'zm_yunjian':'zh-CN-YunjianNeural','zm_yunxi':'zh-CN-YunxiNeural',
    'zm_yunxia':'zh-CN-YunxiaNeural','zm_yunyang':'zh-CN-YunyangNeural',
    'af_bella':'en-US-AvaNeural','af_nicole':'en-US-EmmaNeural',
    'am_michael':'en-US-GuyNeural','am_adam':'en-US-AndrewNeural',
}

def tts_python():return ENGINES/'kokoro-tts-env'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def model_ready(folder,revision):
    try:
        manifest=json.loads((folder/'installed.json').read_text())
        return manifest['revision']==revision and bool(manifest['files']) and all(
            (folder/f['file']).is_file() and (folder/f['file']).stat().st_size==f['size'] for f in manifest['files'])
    except (OSError,ValueError,KeyError):return False

def status():
    import aroll
    azure_ready=importlib.util.find_spec('edge_tts') is not None
    kokoro_ready=tts_python().is_file() and (tts_python().parents[1]/'ready.json').exists() and model_ready(ENGINES/'kokoro-82m',KOKORO_REV)
    providers={AZURE_PROVIDER:{'name':'Azure TTS V1','ready':azure_ready,'online':True},
               KOKORO_PROVIDER:{'name':'Kokoro-82M','ready':kokoro_ready,'online':False}}
    return {'tts':{**providers[AZURE_PROVIDER],'provider':AZURE_PROVIDER},'providers':providers,
            'musetalk':aroll.installation_status(),'speakers':SPEAKERS,'azure_voices':AZURE_VOICES,'languages':LANGUAGES}

def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)

def validate_script(body):
    text=body.get('text','')
    if not isinstance(text,str) or not text.strip() or len(text)>20000 or '\0' in text:
        raise ValueError('请输入 1–20000 字的播客原稿')
    language=body.get('language','Chinese')
    if language not in LANGUAGES:raise ValueError('配音语言无效')
    raw_speaker=str(body.get('speaker') or '').strip()
    provider=str(body.get('provider') or '').strip().lower()
    if not provider:provider=KOKORO_PROVIDER if raw_speaker in SPEAKERS else AZURE_PROVIDER
    if provider==AZURE_PROVIDER:
        speaker=AZURE_LEGACY.get(raw_speaker,raw_speaker) or AZURE_DEFAULT[language]
        if speaker not in AZURE_VOICES[language]:speaker=AZURE_DEFAULT[language]
    elif provider==KOKORO_PROVIDER:
        speaker=LEGACY_SPEAKERS.get(raw_speaker,raw_speaker) or DEFAULT_SPEAKER
        if speaker not in SPEAKERS:raise ValueError('Kokoro 配音声音无效')
        if language=='Chinese' and speaker.startswith(('af_','am_')):speaker=DEFAULT_SPEAKER
        elif language=='English' and speaker.startswith(('zf_','zm_')):speaker='af_bella'
    else:raise ValueError('配音引擎无效')
    try:speed=round(float(body.get('speed',1.0)),2)
    except (TypeError,ValueError):raise ValueError('配音语速无效')
    if speed<.5 or speed>2:raise ValueError('配音语速需在 0.5–2.0 倍之间')
    return {'text':text.strip(),'provider':provider,'speaker':speaker,'language':language,'speed':speed}

def needs_tts(p):
    script=p.get('script')
    if not script:return False
    if not p.get('audio'):return True
    tts=p.get('tts') or {}
    # Completed Qwen/Kokoro projects remain playable. A provider migration must
    # never invalidate audio until the user actually saves a changed script.
    compared=('text','speaker','language')+tuple(k for k in ('provider','speed') if k in script)
    if tts.get('engine') and all(tts.get(key)==script.get(key) for key in compared):
        return False
    try:return tts.get('signature')!=signature(**validate_script(script))
    except (TypeError,ValueError):return True

def synthesize(pid):
    import core as c
    p=c.read_project(pid);script=validate_script(p.get('script') or {})
    provider=script['provider'];provider_status=status()['providers'][provider]
    if not provider_status['ready']:
        if provider==AZURE_PROVIDER:raise ValueError('Azure TTS V1 组件未安装，请重新运行「安装工作台.bat」')
        raise ValueError('请先在「连接与设置」安装本地媒体引擎')
    key=signature(**script);folder=c.project_dir(pid)/'assets/tts'/key;folder.mkdir(parents=True,exist_ok=True)
    request=folder/'request.json';payload={**script,'folder':str(folder)}
    if provider==AZURE_PROVIDER:payload.update(ffmpeg=str(c.FFMPEG),timeout=45)
    else:payload.update(repo_id=KOKORO_REPO,model=str(ENGINES/'kokoro-82m'))
    c.atomic_json(request,payload)
    progress_file=folder/'progress.json';progress_file.unlink(missing_ok=True)
    env=os.environ.copy();env.update(PYTHONIOENCODING='utf-8')
    if provider==KOKORO_PROVIDER:env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    mode='联网 Azure TTS V1' if provider==AZURE_PROVIDER else '本地 Kokoro-82M'
    c.progress(pid,'文字配音',1,f'正在启动{mode}；已完成的段落会复用')
    with (folder/'worker.log').open('wb') as log:
        command=[sys.executable,str(c.ROOT/'azure_tts_worker.py'),str(request)] if provider==AZURE_PROVIDER else [str(tts_python()),str(c.ROOT/'tts_worker.py'),str(request)]
        proc=subprocess.Popen(command,env=env,stdout=log,stderr=log,creationflags=FLAGS)
        began=time.monotonic()
        try:
            while proc.poll() is None:
                pc=1;message='正在加载本地配音模型…'
                try:
                    s=json.loads(progress_file.read_text(encoding='utf-8'));pc=2+94*s['done']/max(1,s['total']);message=s['message']
                except (OSError,ValueError,KeyError):pass
                c.progress(pid,'文字配音',pc,message)
                if time.monotonic()-began>6*3600:raise RuntimeError('配音超过六小时，请缩短原稿；已完成段落保留')
                time.sleep(.5)
            if proc.returncode:
                detail=(folder/'worker.log').read_text(encoding='utf-8',errors='replace')[-1400:]
                prefix='Azure TTS V1 联网配音失败：' if provider==AZURE_PROVIDER else '本地配音失败：'
                raise RuntimeError(prefix+detail)
        finally:stop(proc)
    c.progress(pid,'文字配音',98,'正在建立音轨与原稿字幕时间')
    result=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    master=folder/'master.wav';temp=folder/'master.tmp.wav'
    c.run([c.FFMPEG,'-y','-v','error','-i',folder/'combined.wav','-ac','2','-ar','48000','-c:a','pcm_s16le',temp]);os.replace(temp,master)
    duration=round(c.probe(master)['duration'],3)
    segments=c.normalize_segments(result['segments'],duration);waveform=c.waveform(master)
    with c.LOCK:
        c.progress(pid,'文字配音',99,'配音完成')
        p=c.read_project(pid)
        if p.get('audio'):
            p.setdefault('audio_history',[]).append({k:p.get(k) for k in ('audio','audio_name','tts','duration')})
        label=AZURE_VOICES[script['language']][script['speaker']] if provider==AZURE_PROVIDER else SPEAKERS[script['speaker']]
        p.update(script=script,audio=master.relative_to(c.project_dir(pid)).as_posix(),audio_name=f'文字配音 · {label}.wav',
                 duration=duration,segments=segments,candidate_segments=[],narrative_segments=[],shots=[],analysis=None,waveform=waveform,
                 tts={**result,'signature':key,'text':script['text']},
                 transcription={'engine':result['engine'],'phrase_timing':'awaiting-script-alignment','language':script['language']})
        p['revision']+=1;c.save_project(p)

def install(pid):
    import core as c
    c.progress(pid,'安装本地媒体引擎',0,'首次安装将下载备用本地配音和口型模型，可在失败后继续')
    env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
    logpath=c.DATA/'media-engine-install.log'
    with logpath.open('wb') as log:
        proc=subprocess.Popen([sys.executable,'-u',str(c.ROOT/'engine_setup.py')],env=env,stdout=log,stderr=log,creationflags=FLAGS)
        try:
            while proc.poll() is None:
                with logpath.open('rb') as tail:
                    tail.seek(max(0,logpath.stat().st_size-2000));lines=tail.read().decode('utf-8','replace').splitlines()
                c.progress(pid,'安装本地媒体引擎',0,(lines[-1] if lines else '正在准备下载…')[:400]);time.sleep(1)
            if proc.returncode:raise RuntimeError('安装未完成，可点击继续重试。'+logpath.read_text(encoding='utf-8',errors='replace')[-1000:])
        finally:
            if proc.poll() is None and os.name=='nt':
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=FLAGS)
            stop(proc)
