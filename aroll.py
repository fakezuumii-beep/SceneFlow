"""Workbench-owned MuseTalk 1.5 adapter with no ComfyUI dependency."""
from __future__ import annotations
import hashlib, json, math, os, subprocess, time, uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ENGINES=ROOT/'engines'
FPS=25
CONTEXT=.2
ADAPTER_VERSION='musetalk15-direct-static-v2'
VIDEO_ADAPTER_VERSION='musetalk15-direct-video-v4-shared-runs'
DEFAULT_PROVIDER_IDENTITY={'provider':'musetalk','provider_version':'musetalk15-provider-v1','model':'MuseTalk 1.5',
                           'adapter':VIDEO_ADAPTER_VERSION+'|'+ADAPTER_VERSION,'workflow_hash':None}

def media_python():return ENGINES/'media-env'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

def batch_size():
    """Frames per inference batch: the only MuseTalk knob that trades VRAM for speed."""
    import core as c
    return c._aroll_batch_size(c.settings(True))

def video_source(p):
    import core as c
    return c.host_media(p).suffix.lower() in ('.mp4','.mov','.mkv','.webm','.m4v')

def required_files():
    repo=ENGINES/'MuseTalk';models=repo/'models'
    return [repo/'musetalk/models/unet.py',models/'musetalkV15/unet.pth',models/'musetalkV15/musetalk.json',
            models/'sd-vae/config.json',models/'sd-vae/diffusion_pytorch_model.bin',models/'whisper/config.json',
            models/'whisper/pytorch_model.bin',models/'whisper/preprocessor_config.json',models/'face_detection_yunet_2023mar.onnx']

def installation_status(check_online=False):
    missing=[x.relative_to(ROOT).as_posix() for x in required_files() if not x.is_file() or x.stat().st_size<100]
    runtime_marker=media_python().parents[1]/'ready.json'
    ready=media_python().is_file() and runtime_marker.is_file() and not missing
    return {'engine':'MuseTalk 1.5','installed':ready,'online':ready,'adapter':ADAPTER_VERSION,
            'message':'独立引擎已就绪 · 25fps · 本地 GPU' if ready else ('缺少：'+', '.join(missing[:3]) if missing else '独立媒体环境尚未安装'),
            'runtime':'standalone','comfyui':False}

def stamp(path):
    stat=path.stat();return [str(path),stat.st_size,stat.st_mtime_ns]

def contiguous_runs(shots):
    """Return timeline-adjacent A-roll shots that must share one inference pass."""
    runs=[];current=[]
    for shot in shots:
        adjacent=(current and shot.get('kind')=='A' and
                  abs(float(shot['start'])-float(current[-1]['end']))<=.002)
        if shot.get('kind')=='A':
            if not adjacent and current:runs.append(current);current=[]
            current.append(shot)
        elif current:
            runs.append(current);current=[]
    if current:runs.append(current)
    return runs

def shot_run(p,s):
    return next((run for run in contiguous_runs(p.get('shots',[])) if any(x.get('id')==s.get('id') for x in run)),[s])

def run_signature(p,run,provider_identity=None):
    import core as c
    if not p.get('audio'):return ''
    content=[provider_identity or DEFAULT_PROVIDER_IDENTITY,VIDEO_ADAPTER_VERSION if video_source(p) else ADAPTER_VERSION,stamp(c.asset_path(p['id'],p['audio'])),
             stamp(c.host_media(p)),run[0]['start'],run[-1]['end'],FPS,CONTEXT]
    return hashlib.sha256(json.dumps(content,ensure_ascii=False).encode()).hexdigest()[:24]

def signature(p,s,provider_identity=None):
    if not p.get('audio'):return ''
    content=[run_signature(p,shot_run(p,s),provider_identity),s['start'],s['end']]
    return hashlib.sha256(json.dumps(content,ensure_ascii=False).encode()).hexdigest()[:24]

def is_ready(p,s,provider_identity=None):
    import core as c
    return bool(s.get('aroll_asset') and s.get('aroll_signature')==signature(p,s,provider_identity)
                and (c.project_dir(p['id'])/s['aroll_asset']).is_file())

def decorate(p):
    import core as c
    folder=c.project_dir(p['id'])
    p['host_asset']=c.host_image(p).relative_to(folder).as_posix()
    media=c.host_media(p)
    p['host_media_asset']=media.relative_to(folder).as_posix()
    p['host_media_kind']='video' if media.suffix.lower() in ('.mp4','.mov','.mkv','.webm','.m4v') else 'image'
    for s in p['shots']:
        if s['kind']=='A':s['aroll_ready']=is_ready(p,s)
    return p

def prepare_video_chunk(source,target,start,duration):
    """Create a frame-aligned forward loop at the absolute podcast time."""
    import core as c
    frames=math.ceil(duration*FPS)+2
    if valid_chunk(target,frames):return
    temp=target.with_suffix('.part.mp4');loop_duration=c.probe(source)['duration']
    phase=(round(start*FPS)%max(1,round(loop_duration*FPS)))/FPS
    c.run([c.FFMPEG,'-y','-v','error','-stream_loop','-1','-i',source,'-an',
           '-vf',f'fps={FPS},trim=start_frame={round(phase*FPS)},setpts=PTS-STARTPTS','-frames:v',str(frames),
           '-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-threads','4','-movflags','+faststart',temp])
    if not valid_chunk(temp,frames):raise RuntimeError('循环视频片段帧数校验失败')
    temp.replace(target)

def valid_chunk(path,frames):
    import core as c
    if not path.is_file():return False
    try:
        info=c.probe(path);video=next((s for s in info['streams'] if s['codec_type']=='video'),None)
        return bool(video and int(video.get('nb_frames',0))==frames)
    except (ValueError,RuntimeError,OSError):return False

def valid_video(path,expected_duration=None):
    import core as c
    if not path.is_file():return False
    try:
        info=c.probe(path)
        return (info['duration']>0 and any(s['codec_type']=='video' for s in info['streams'])
                and (expected_duration is None or abs(info['duration']-expected_duration)<=.12))
    except (ValueError,RuntimeError,OSError):return False

def trim_chunk(raw,target,offset,frames):
    return trim_chunk_frames(raw,target,round(offset*FPS),frames)

def trim_chunk_frames(raw,target,start_frame,frames):
    import core as c
    temp=target.with_suffix('.part.mp4')
    c.run([c.FFMPEG,'-y','-v','error','-i',raw,'-an','-vf',
           f'tpad=stop_mode=clone:stop_duration=0.24,trim=start_frame={start_frame}:end_frame={start_frame+frames},setpts=PTS-STARTPTS,fps={FPS}',
           '-frames:v',str(frames),'-c:v','libx264','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-threads','4',temp])
    if not valid_chunk(temp,frames):raise RuntimeError('A-roll 片段帧数不足，已保留原始推理结果以便重试')
    temp.replace(target)

def stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=10)

OOM_HINTS=('CUDA out of memory','CUDNN_STATUS_ALLOC_FAILED','out of memory','OutOfMemoryError')

def run_worker(pid,request,progress_file):
    """Run MuseTalk, halving the frame batch whenever the GPU runs out of memory."""
    import core as c
    batch=min(task.get('batch_size',8) for task in request['tasks'])
    for attempt in range(4):
        detail=_run_worker_once(pid,request,progress_file)
        if detail is None:return
        smaller=batch//2
        if smaller<1 or not any(hint in detail for hint in OOM_HINTS):
            raise RuntimeError('独立 MuseTalk 失败：'+detail)
        batch=smaller
        for task in request['tasks']:task['batch_size']=batch
        c.progress(pid,'A-roll 对口型',3,f'显存不足，已降到每批 {batch} 帧重试')
    raise RuntimeError('独立 MuseTalk 失败：'+detail)

def _run_worker_once(pid,request,progress_file):
    import core as c
    request_file=progress_file.with_name('request.json');c.atomic_json(request_file,request)
    logpath=progress_file.with_name('worker.log');progress_file.unlink(missing_ok=True)
    env=os.environ.copy();env.update(PYTHONIOENCODING='utf-8',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    with logpath.open('wb') as log:
        proc=subprocess.Popen([str(media_python()),str(ROOT/'musetalk_worker.py'),str(request_file)],cwd=ROOT,env=env,
                              stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        began=time.monotonic()
        try:
            while proc.poll() is None:
                if c.ACTIVE.get(pid,{}).get('cancel'):
                    stop(proc);raise RuntimeError('已停止；完成的口型缓存会在下次继续使用')
                message='正在加载独立 MuseTalk 1.5 模型…';percent=2
                try:
                    state=json.loads(progress_file.read_text(encoding='utf-8'));message=state.get('message',message)
                    task=state.get('task',0);tasks=max(1,state.get('tasks',len(request['tasks'])));batch=state.get('batch',0);batches=max(1,state.get('batches',1))
                    percent=3+92*((task-1+batch/batches)/tasks) if task else 2
                except (OSError,ValueError,KeyError):pass
                c.progress(pid,'A-roll 对口型',percent,message)
                if time.monotonic()-began>6*3600:raise RuntimeError('MuseTalk 推理超过六小时；缓存已保留，可重试')
                time.sleep(.5)
            if proc.returncode:
                return logpath.read_text(encoding='utf-8',errors='replace')[-1800:]
        finally:stop(proc)

def generate(pid,shot_id=None,provider_identity=None):
    import core as c
    p=c.read_project(pid);runs=contiguous_runs(p['shots'])
    if shot_id and not any(any(s['id']==shot_id for s in run) for run in runs):raise ValueError('未找到选中的 A-roll 镜头')
    provider_identity=provider_identity or DEFAULT_PROVIDER_IDENTITY
    pending=[run for run in runs if ((not shot_id and any(not is_ready(p,s,provider_identity) for s in run)) or
                                     (shot_id and any(s['id']==shot_id for s in run)))]
    if not pending:return
    if not installation_status()['installed']:raise ValueError('MuseTalk 独立引擎尚未安装，请在「连接与设置」安装本地媒体引擎')
    c.validate_timeline(p['shots'],p['duration']);folder=c.project_dir(pid);is_video=video_source(p);prepared=[]
    for run in pending:
        stable=run_signature(p,run,provider_identity);suffix=('-'+uuid.uuid4().hex[:6] if shot_id else '');base=stable+suffix
        cache=folder/'aroll-cache'/base;cache.mkdir(parents=True,exist_ok=True)
        context_start=max(0,float(run[0]['start'])-CONTEXT);context_end=min(p['duration'],float(run[-1]['end'])+CONTEXT)
        audio=cache/'audio.wav'
        if not audio.exists():c.run([c.FFMPEG,'-y','-v','error','-ss',str(context_start),'-i',c.asset_path(pid,p['audio']),'-t',str(context_end-context_start),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',audio])
        if is_video:
            source=cache/'host.mp4';prepare_video_chunk(c.host_media(p),source,context_start,context_end-context_start)
        else:
            source=cache/'host.jpg'
            if not source.exists():
                from PIL import Image,ImageOps
                with Image.open(c.host_image(p)) as image:ImageOps.fit(image.convert('RGB'),(1920,1080),method=Image.Resampling.LANCZOS).save(source,quality=95)
        items=[]
        for s in run:
            sig=signature(p,s,provider_identity);start_frame=round((float(s['start'])-context_start)*FPS)
            end_frame=round((float(s['end'])-context_start)*FPS);frames=end_frame-start_frame
            items.append({'shot':s,'signature':sig,'frames':frames,'start_frame':start_frame})
        prepared.append({'run':run,'cache':cache,'raw':cache/'raw.mp4','duration':context_end-context_start,
                         'context_start':context_start,'context_end':context_end,'source':source,'audio':audio,'items':items,
                         'asset_key':stable+suffix})
    batch=batch_size()
    tasks=[{'video':str(x['source']),'audio':str(x['audio']),'output':str(x['raw']),'ffmpeg':str(c.FFMPEG),'batch_size':batch}
           for x in prepared if not valid_video(x['raw'],c.probe(x['audio'])['duration'])]
    if tasks:
        runroot=folder/'aroll-cache'/('run-'+uuid.uuid4().hex[:10]);runroot.mkdir(parents=True,exist_ok=True)
        run_worker(pid,{'repo':str(ENGINES/'MuseTalk'),'progress':str(runroot/'progress.json'),'tasks':tasks},runroot/'progress.json')
    total=sum(len(x['items']) for x in prepared);written=0
    for run_item in prepared:
        run_start_frame=run_item['items'][0]['start_frame']
        run_end_frame=run_item['items'][-1]['start_frame']+run_item['items'][-1]['frames']
        run_frames=run_end_frame-run_start_frame;finished=run_item['cache']/'finished-run.mp4'
        try:
            if not valid_chunk(finished,run_frames):trim_chunk_frames(run_item['raw'],finished,run_start_frame,run_frames)
            asset=folder/'assets'/f'aroll-run-{run_item["asset_key"]}.mp4';temp=asset.with_suffix('.part.mp4')
            c.run([c.FFMPEG,'-y','-v','error','-i',finished,'-an','-c:v','copy','-movflags','+faststart',temp])
            info=c.probe(temp);expected=run_frames/FPS
            if abs(info['duration']-expected)>.04:raise RuntimeError('A-roll 连续片段时长校验失败')
            temp.replace(asset)
            for item in run_item['items']:
                with c.LOCK:
                    current=c.read_project(pid);target=next(x for x in current['shots'] if x['id']==item['shot']['id'])
                    if target.get('aroll_asset') and target['aroll_asset']!=asset.relative_to(folder).as_posix():
                        target.setdefault('aroll_history',[]).append({'asset':target['aroll_asset'],'signature':target.get('aroll_signature')})
                    target.update(aroll_asset=asset.relative_to(folder).as_posix(),aroll_signature=item['signature'],aroll_status='ready',aroll_error=None,
                        aroll_provenance={'provider':provider_identity['provider'],'engine':'MuseTalk 1.5','runtime':'local',
                        'provider_version':provider_identity['provider_version'],'model':provider_identity.get('model'),
                        'workflow_hash':provider_identity.get('workflow_hash'),'adapter':VIDEO_ADAPTER_VERSION if is_video else ADAPTER_VERSION,
                        'source':c.host_media(p).relative_to(folder).as_posix(),'source_kind':'video' if is_video else 'image',
                        'loop_mode':'forward' if is_video else None,'fps':FPS,'duration':item['frames']/FPS,'continuous_asset_duration':info['duration'],
                        'audio_start':item['shot']['start'],'audio_end':item['shot']['end'],'continuous_run_start':run_item['run'][0]['start'],
                        'continuous_run_end':run_item['run'][-1]['end']},
                        aroll_media_start=(item['start_frame']-run_start_frame)/FPS)
                    current['revision']+=1;c.save_project(current)
                written+=1;c.progress(pid,'A-roll 对口型',96+3*written/total,f'已写入口型 {written}/{total}')
        except Exception as exc:
            with c.LOCK:
                current=c.read_project(pid)
                for item in run_item['items']:
                    target=next(x for x in current['shots'] if x['id']==item['shot']['id'])
                    target.update(aroll_status='error',aroll_error=c.safe_error(exc))
                c.save_project(current)
            raise
