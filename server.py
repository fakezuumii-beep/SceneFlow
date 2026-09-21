from __future__ import annotations
import copy, hashlib, json, math, mimetypes, os, re, shutil, time, uuid
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image, ImageOps
import core as c
import auto_edit as ae
import morning_bridge
from providers import public_catalog
from providers.llm import resolve_llm_config, test_connection as test_llm_connection
from providers.broll import resolve_broll_config, test_connection as test_broll_connection
from providers.aroll import decorate_project, get_aroll_provider, get_project_aroll_provider
LOADED_REVISION=c.code_revision()

@asynccontextmanager
async def lifespan(app):
    c.recover_jobs()
    yield

app=FastAPI(title='SceneFlow — AI Automatic Podcast Video Workbench',docs_url='/api/docs',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','testserver'])

@app.middleware('http')
async def local_only(request:Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        port=os.environ.get('SOLO_PORT','8766')
        if origin and origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):
            return JSONResponse({'detail':'仅允许本地工作台提交修改'},status_code=403)
    return await call_next(request)

@app.exception_handler(ValueError)
async def value_error(request,exc): return JSONResponse({'detail':c.safe_error(exc)},status_code=400)

@app.exception_handler(RuntimeError)
async def runtime_error(request,exc): return JSONResponse({'detail':c.safe_error(exc)},status_code=400)

@app.get('/api/settings')
def get_settings(): return c.settings()


@app.get('/api/providers')
def providers(): return public_catalog()


@app.get('/api/providers/status')
def provider_status(project_id:str=''):
    cfg=c.settings(True);llm=resolve_llm_config(cfg);broll=resolve_broll_config(cfg)
    project=c.read_project(project_id) if project_id else None
    aroll_provider=get_project_aroll_provider(cfg,project) if project else get_aroll_provider(cfg)
    return {'llm':{'id':llm['provider'],'name':llm['name'],'configured':bool(llm['api_key'])},
            'broll':{'id':broll['provider'],'name':broll['name'],'configured':bool(broll['api_key'])},
            'aroll':{'id':aroll_provider.id,'name':aroll_provider.name,'short_name':aroll_provider.short_name,**aroll_provider.status()}}

@app.get('/api/health')
def health():
    return {'status':'ok','revision':LOADED_REVISION,'update_required':LOADED_REVISION!=c.code_revision(),
            'features':{'reliable_planning':True,'semantic_rule_planning':True,'musetalk':True,'direct_musetalk':True,
                        'latentsync16':True,
                        'wav2lip_on_demand':True,'deepseek_api':True,'text_to_video':True,'ai_business_briefing':True,
                        'deterministic_edit_plan':True,'auto_edit_export':True,
                        'visual_director':True,'visual_master_plan':True,'visual_roles':True,
                        'stock_asset_resolver':True,'evidence_resolver':True,'motion_router':True,
                        'visual_rhythm':True,'evidence_screenshot':True,
                        'generated_scene_h3':True,'h3_multiref_generation':True,
                        'unified_visual_timeline':True,
                        'five_route_execution':True}}

# Stable, short health URL used by the Windows launcher and smoke tests.  Keep
# the API form above for backwards compatibility with existing clients.
@app.get('/health')
def short_health():
    return health()

@app.get('/api/local-models')
def local_models():
    import local_engines
    return local_engines.status()


@app.get('/api/morning-briefing')
def morning_briefing():
    return morning_bridge.read_current()


@app.post('/api/morning-briefing/generate')
def generate_morning_briefing():
    if c.ACTIVE:
        raise ValueError('视频任务正在处理，请完成后再生成晨报')
    return morning_bridge.generate()


@app.post('/api/morning-briefing/confirm')
def confirm_morning_briefing(body:dict):
    project,reused=morning_bridge.import_project(
        c, str(body.get('generation_id') or ''),
        str(body.get('speaker') or 'zh-CN-XiaoxiaoNeural'), body.get('speed',1.0),
    )
    return {'project_id':project['id'],'reused':reused}

@app.put('/api/projects/{pid}/script')
def save_script(pid:str,body:dict):
    import local_engines
    with c.LOCK:
        c.ensure_idle(pid);p=c.read_project(pid)
        draft=dict(body)
        provider=str(draft.get('provider') or '').strip().lower()
        speaker=str(draft.get('speaker') or '').strip()
        if provider=='indextts25' or (provider=='seed-audio' and speaker=='seed-reference'):
            draft['reference']=p.get('voice_reference') or draft.get('reference') or ''
        script=local_engines.validate_script(draft)
        if p.get('script')!=script:
            p['script']=script
            p['script_defaults']={key:script[key] for key in ('provider','speaker','language','speed','reference')}
            p['revision']+=1;c.save_project(p)
        return p

@app.get('/api/aroll/status')
def aroll_status():return get_aroll_provider(c.settings(True)).status(True)

@app.put('/api/settings')
def put_settings(body:dict):
    with c.LOCK:
        if c.ACTIVE: raise ValueError('任务运行中，请完成后再修改连接设置')
        return c.save_settings(body)


@app.post('/api/settings/wav2lip-license')
def acknowledge_wav2lip_license(body:dict):
    with c.LOCK:
        if c.ACTIVE:raise ValueError('任务运行中，请完成后再确认安装')
        return c.acknowledge_wav2lip_license(body.get('acknowledged'))


@app.post('/api/settings/wav2lip-model')
def upload_wav2lip_model(file:UploadFile=File(...)):
    import wav2lip_setup as setup
    if Path(file.filename or '').suffix.lower() not in ('.pt','.pth'):
        raise ValueError('请选择官方 Wav2Lip-SD-GAN.pt 模型文件')
    folder=setup.ENGINES/'downloads';folder.mkdir(parents=True,exist_ok=True)
    target=folder/f'manual-{setup.CHECKPOINT_NAME}';temporary=target.with_suffix(target.suffix+'.part')
    size=0
    try:
        with temporary.open('wb') as stream:
            while chunk:=file.file.read(2*1024*1024):
                size+=len(chunk)
                if size>setup.CHECKPOINT_SIZE+1:raise ValueError('所选模型文件大小不正确')
                stream.write(chunk)
        if not setup.verified(temporary,setup.CHECKPOINT_SIZE,setup.CHECKPOINT_SHA256):
            raise ValueError('所选文件不是当前支持的官方 Wav2Lip-SD-GAN.pt（SHA256 不匹配）')
        os.replace(temporary,target)
        return {'ok':True,'message':'官方 Wav2Lip 模型已校验，点击安装即可继续'}
    finally:
        temporary.unlink(missing_ok=True)


def temporary_settings(body):
    cfg=c.settings(True);allowed=set(c._settings_defaults())
    for key,value in body.items():
        if key not in allowed:continue
        if key.endswith('api_key') and not value:continue
        cfg[key]=value
    return cfg


@app.post('/api/settings/test')
def test_settings(body:dict):
    cfg=temporary_settings(body);kind=str(body.get('type') or '')
    if kind=='llm':return test_llm_connection(cfg)
    if kind=='broll':return test_broll_connection(cfg)
    if kind=='aroll':
        provider=get_aroll_provider(cfg)
        if hasattr(provider,'test_connection'):return provider.test_connection()
        status=provider.status(True)
        if not status.get('ready'):raise ValueError(f'{provider.name} 尚未就绪：{status.get("message","")}')
        return {'ok':True,'message':f'{provider.name} 已就绪'}
    if kind in ('tts_seed','tts_index'):
        import local_engines
        provider='seed-audio' if kind=='tts_seed' else 'indextts25'
        return local_engines.test_provider_connection(provider,cfg)
    raise ValueError('请选择要测试的服务')


@app.post('/api/settings/aroll-workflow')
def upload_aroll_workflow(file:UploadFile=File(...)):
    raw=file.file.read(5*1024*1024+1)
    if len(raw)>5*1024*1024:raise ValueError('工作流文件不能超过 5 MB')
    try: workflow=json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError,json.JSONDecodeError):raise ValueError('请选择有效的 workflow_api.json') from None
    if not isinstance(workflow,dict) or not workflow:raise ValueError('工作流必须是非空 JSON 对象')
    digest=hashlib.sha256(json.dumps(workflow,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    folder=c.PRIVATE/'workflows';folder.mkdir(exist_ok=True);path=folder/f'{digest}.json';c.atomic_json(path,workflow)
    return c.save_settings({'aroll_comfyui_workflow':f'workflows/{digest}.json','aroll_comfyui_workflow_hash':digest})

@app.get('/api/projects')
def projects():
    result=[]
    for path in c.PROJECTS.glob('*/project.json'):
        p=c.read_project(path.parent.name)
        result.append({k:p.get(k) for k in ('id','name','duration','updated_at','job')})
    return sorted(result,key=lambda p:p['updated_at'],reverse=True)

@app.post('/api/projects')
def create(body:dict): return c.create_project(str(body.get('name','我的第一期播客')))

@app.delete('/api/projects/{pid}')
def delete_project(pid:str): return c.delete_project(pid)

@app.get('/api/projects/{pid}')
def project(pid:str):
    p=c.read_project(pid); p['captions']=c.subtitle_events(p)
    p['edit_plan_current']=ae.plan_is_current(p)
    return decorate_project(p,c.settings(True))

@app.patch('/api/projects/{pid}')
def patch_project(pid:str,body:dict):
    with c.LOCK:
        c.ensure_idle(pid); p=c.read_project(pid)
        if 'name' in body: p['name']=str(body['name']).strip()[:120] or '未命名播客'
        if 'aroll_provider_id' in body:
            selected=str(body['aroll_provider_id'] or '').strip().lower()
            if selected not in ('wav2lip','musetalk','latentsync','infinitetalk','autodl_h3','custom'):
                raise ValueError('请选择支持的 A-roll 方案')
            p['aroll_provider_id']=selected
            p['aroll_provider_scope_version']=1
        if 'options' in body:
            old_aspect=p['options'].get('aspect_ratio','16:9');options={**p['options'],**body['options']}
            options={k:options[k] for k in p['options']}
            if (options['resolution'] not in ('720p','1080p') or options['aspect_ratio'] not in ('16:9','1:1','9:16')
                    or options['workflow_mode'] not in ('direct','two_step')
                    or options['source'] not in ('global','pexels','pixabay')): raise ValueError('设置选项无效')
            if not 0<=int(options['broll_ratio'])<=80 or not 6<=int(options['max_shot'])<=40: raise ValueError('分镜偏好超出范围')
            options['broll_ratio']=int(options['broll_ratio']); options['max_shot']=int(options['max_shot']); options['subtitles']=bool(options['subtitles'])
            for key in ('auto_edit_enabled','auto_edit_remove_pauses','auto_edit_highlights','auto_edit_cards','bgm_enabled'):
                options[key]=bool(options[key])
            options['auto_edit_pause_threshold']=round(float(options['auto_edit_pause_threshold']),2)
            options['auto_edit_pause_padding']=round(float(options['auto_edit_pause_padding']),2)
            options['bgm_volume']=round(float(options['bgm_volume']),2)
            if not .35<=options['auto_edit_pause_threshold']<=3:
                raise ValueError('停顿剪切阈值需在 0.35 到 3 秒之间')
            if not 0<=options['auto_edit_pause_padding']<=.3:
                raise ValueError('停顿保留边缘需在 0 到 0.3 秒之间')
            if not .02<=options['bgm_volume']<=.5:
                raise ValueError('背景音乐音量需在 2% 到 50% 之间')
            c.switch_broll_aspect(p,old_aspect,options['aspect_ratio'])
            p['options']=options
        p['revision']+=1; c.save_project(p); return p

@app.post('/api/projects/{pid}/upload')
def upload(pid:str,kind:str=Form(...),file:UploadFile=File(...),shot_id:str=Form('')):
    with operation(pid,'导入素材'):
        p=c.read_project(pid); folder=c.project_dir(pid)
        ext=Path(file.filename or '').suffix.lower()
        if kind in ('audio','voice_reference','reference_audio','bgm'): allowed={'.mp3','.wav','.m4a','.aac','.flac','.ogg','.mp4','.webm'}
        elif kind=='portrait': allowed={'.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv','.webm','.m4v'}
        elif kind=='broll': allowed={'.mp4','.mov','.mkv','.webm','.m4v','.png','.jpg','.jpeg','.webp'}
        elif kind=='reference': allowed={'.png','.jpg','.jpeg','.webp'}
        elif kind=='srt': allowed={'.srt'}
        else: raise ValueError('不支持的素材类型')
        if ext not in allowed: raise ValueError('文件格式不支持')
        token=uuid.uuid4().hex[:12]; target=folder/'assets'/f'{kind}-{token}{ext}'
        size=0
        try:
            with target.open('wb') as f:
                while chunk:=file.file.read(1024*1024):
                    size+=len(chunk)
                    limit=30*1024**2 if kind=='voice_reference' else 500*1024**2 if kind=='bgm' else 2*1024**3
                    if size>limit: raise ValueError('参考声音不能超过 30 MB' if kind=='voice_reference' else '背景音乐不能超过 500 MB' if kind=='bgm' else '文件超过 2 GB')
                    f.write(chunk)
            if kind=='audio':
                info=c.probe(target)
                if not any(s['codec_type']=='audio' for s in info['streams']) or info['duration']<=0: raise ValueError('没有找到有效音轨')
                if info['duration']>4*3600: raise ValueError('第一版支持最长 4 小时音频')
                # Browser and renderer use the same normalized PCM master, with no content edits.
                audio=target.with_suffix('.master.wav')
                c.run([c.FFMPEG,'-y','-v','error','-i',target,'-vn','-ac','2','-ar','48000','-c:a','pcm_s16le',audio],timeout=1800)
                p.update(audio=str(audio.relative_to(folder)).replace('\\','/'),audio_name=file.filename,
                         duration=round(c.probe(audio)['duration'],3),segments=[],candidate_segments=[],narrative_segments=[],shots=[],analysis=None,waveform=c.waveform(audio),edit_plan=None)
                p.pop('script',None);p.pop('tts',None)
            elif kind=='voice_reference':
                source=target
                info=c.probe(target)
                if not any(s['codec_type']=='audio' for s in info['streams']) or info['duration']<=0:
                    raise ValueError('参考声音中没有找到有效音轨')
                if info['duration']>120:raise ValueError('参考声音请控制在 2 分钟以内')
                normalized=folder/'assets'/f'voice-reference-{token}.wav'
                c.run([c.FFMPEG,'-y','-v','error','-i',target,'-vn','-ac','1','-ar','24000',
                       '-c:a','pcm_s16le',normalized],timeout=300)
                target=normalized
                source.unlink(missing_ok=True)
                relative=target.relative_to(folder).as_posix()
                p.update(voice_reference=relative,voice_reference_name=file.filename)
                script=p.get('script') or {}
                if (script.get('provider')=='indextts25' or
                        (script.get('provider')=='seed-audio' and script.get('speaker')=='seed-reference')):
                    script['reference']=relative
                    p['script_defaults']={key:script.get(key) for key in ('provider','speaker','language','speed','reference')}
            elif kind=='reference_audio':
                info=c.probe(target)
                if not any(s['codec_type']=='audio' for s in info['streams']) or info['duration']<=0:
                    raise ValueError('H3 参考音频中没有有效音轨')
                normalized=folder/'assets'/f'reference-audio-{token}.wav'
                c.run([c.FFMPEG,'-y','-v','error','-i',target,'-vn','-ac','1','-ar','24000',
                       '-c:a','pcm_s16le',normalized],timeout=300)
                target.unlink(missing_ok=True);target=normalized
                relative=target.relative_to(folder).as_posix()
                shot=next((s for s in p['shots'] if s['id']==shot_id),None)
                if not shot:raise ValueError('镜头不存在')
                values=shot.setdefault('reference_audios',[])
                if relative not in values:values.append(relative)
            elif kind=='bgm':
                info=c.probe(target)
                if not any(s['codec_type']=='audio' for s in info['streams']) or info['duration']<=0:
                    raise ValueError('背景音乐中没有找到有效音轨')
                if info['duration']>3600:raise ValueError('背景音乐请控制在 1 小时以内')
                normalized=folder/'assets'/f'bgm-{token}.m4a'
                c.run([c.FFMPEG,'-y','-v','error','-i',target,'-vn','-ar','48000','-ac','2',
                       '-c:a','aac','-b:a','192k',normalized],timeout=600)
                target.unlink(missing_ok=True);target=normalized
                p.update(bgm=target.relative_to(folder).as_posix(),bgm_name=file.filename,edit_plan=None)
                p['options']['bgm_enabled']=True
            elif kind in ('portrait','broll','reference'):
                is_image=ext in ('.png','.jpg','.jpeg','.webp')
                if kind=='reference' and not is_image:raise ValueError('生成参考图必须是图片')
                if is_image:
                    normalized=folder/'assets'/f'{kind}-{token}.normalized.jpg'
                    with Image.open(target) as image:
                        image=ImageOps.exif_transpose(image).convert('RGB'); image.thumbnail((3840,3840)); image.save(normalized,quality=95)
                    target=normalized
                    duration=0
                else:
                    info=c.probe(target)
                    if not any(s['codec_type']=='video' for s in info['streams']) or info['duration']<=0: raise ValueError('视频无有效画面')
                    normalized=folder/'assets'/f'{kind}-{token}.preview.mp4'
                    filters='scale=1920:1080:force_original_aspect_ratio=decrease:force_divisible_by=2,setsar=1'
                    if kind=='portrait': filters+=',fps=25'
                    c.run([c.FFMPEG,'-y','-v','error','-i',target,'-an','-vf',filters,'-c:v','libx264','-preset','veryfast','-crf','19','-pix_fmt','yuv420p','-threads','4','-movflags','+faststart',normalized])
                    target=normalized; duration=info['duration']
                relative=str(target.relative_to(folder)).replace('\\','/')
                if kind=='reference':
                    shot=next((s for s in p['shots'] if s['id']==shot_id),None)
                    if not shot: raise ValueError('镜头不存在')
                    shot['reference_image']=relative
                    references=shot.setdefault('reference_images',[])
                    if relative not in references:references.append(relative)
                elif kind=='portrait':
                    p.update(portrait=relative,portrait_name=file.filename,portrait_kind='image' if is_image else 'video',portrait_duration=duration,portrait_poster=None)
                    if not is_image:
                        poster=folder/'assets'/f'{kind}-{token}.poster.jpg'
                        c.run([c.FFMPEG,'-y','-v','error','-i',target,'-frames:v','1',poster])
                        p['portrait_poster']=poster.relative_to(folder).as_posix()
                else:
                    shot=next((s for s in p['shots'] if s['id']==shot_id),None)
                    if not shot: raise ValueError('镜头不存在')
                    shot.update(kind='B',asset=relative,source={'provider':'local','author':'本地导入','page':'','duration':duration,'name':file.filename},media_start=0,material_status='ready',material_error=None)
            else:
                if not p['audio']: raise ValueError('请先导入音频，才能校验字幕时间')
                raw=target.read_bytes()
                try: text=raw.decode('utf-8-sig')
                except UnicodeDecodeError: text=raw.decode('gb18030')
                p['segments']=c.parse_srt(text,p['duration']);p['candidate_segments']=copy.deepcopy(p['segments']);p['narrative_segments']=[];p['shots']=[];p['analysis']=None;p['transcription']={'engine':'导入 SRT','phrase_timing':'srt-cue-v1'}
            p['revision']+=1
            # Preserve operation's current job state.
            p['job']=c.read_project(pid)['job']; c.save_project(p)
            return p
        except Exception:
            # Only the just-uploaded file is eligible for cleanup, never old project assets.
            target.unlink(missing_ok=True)
            raise

@app.get('/api/host-materials')
def host_materials():
    allowed=('.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv','.webm','.m4v')
    builtin_folder=c.ROOT/'assets'/'hosts'
    result=[{'name':'builtin:'+item['filename'],'label':item['label'],'source':'builtin'}
            for item in c.BUILTIN_HOST_VIDEOS
            if (builtin_folder/item['filename']).is_file()]
    folder=c.ROOT/'我的素材'
    if folder.is_dir():
        result.extend({'name':path.name,'label':path.name,'source':'library'}
                      for path in sorted(folder.iterdir()) if path.is_file() and path.suffix.lower() in allowed)
    return result


@app.get('/api/projects/{pid}/edit-plan')
def edit_plan(pid:str):
    p=c.read_project(pid)
    return {'current':ae.plan_is_current(p),'plan':p.get('edit_plan')}


@app.post('/api/projects/{pid}/edit-plan')
def generate_edit_plan(pid:str):
    with operation(pid,'生成自动精剪计划','plan'):
        return c.create_edit_plan(pid)

@app.post('/api/projects/{pid}/host-material')
def use_host_material(pid:str,body:dict):
    name=str(body.get('name',''))
    if name.startswith('builtin:'):
        filename=name.removeprefix('builtin:')
        known={item['filename'] for item in c.BUILTIN_HOST_VIDEOS}
        if filename not in known:raise ValueError('未找到所选人物素材')
        folder=(c.ROOT/'assets'/'hosts').resolve();path=(folder/filename).resolve()
    else:
        folder=(c.ROOT/'我的素材').resolve();path=(folder/name).resolve()
    if not name or path.parent!=folder or not path.is_file():raise ValueError('未找到所选人物素材')
    with path.open('rb') as f:
        return upload(pid,kind='portrait',file=UploadFile(file=f,filename=path.name),shot_id='')

@contextmanager
def operation(pid,label,resource=None):
    with c.LOCK:
        c.ensure_idle(pid)
        p=c.read_project(pid)
        p['job']={'action':label,'stage':label,'status':'running','progress':0,'message':label+'…','started_at':time.time()}; c.save_project(p)
        c.ACTIVE[pid]={'cancel':False}
    try:
        if resource:
            with c.stage_slot(pid,resource,label):yield
        else:
            yield
        with c.LOCK:
            p=c.read_project(pid); p['job'].update(status='done',progress=100,message=label+'完成'); c.save_project(p)
    except Exception as exc:
        with c.LOCK:
            p=c.read_project(pid); p['job'].update(status='error',message=c.safe_error(exc)); c.save_project(p)
        raise
    finally:
        with c.LOCK: c.ACTIVE.pop(pid,None)

@app.post('/api/projects/{pid}/jobs')
def job(pid:str,body:dict): return c.start_job(pid,body.get('action'),body.get('shot_id'))


@app.get('/api/projects/{pid}/preflight')
def preflight(pid:str,action:str='all'):return c.generation_preflight(c.read_project(pid),action)

@app.post('/api/projects/{pid}/cancel')
def cancel(pid:str):
    with c.LOCK:
        if pid in c.ACTIVE: c.ACTIVE[pid]['cancel']=True
    try:get_project_aroll_provider(c.settings(True),c.read_project(pid)).cancel(pid)
    except Exception:pass
    return {'message':'将在当前处理步骤结束后停止，已完成内容会保留'}

@app.patch('/api/projects/{pid}/shots/{sid}')
def patch_shot(pid:str,sid:str,body:dict):
    with c.LOCK:
        c.ensure_idle(pid); p=c.read_project(pid); index=next((i for i,s in enumerate(p['shots']) if s['id']==sid),None)
        if index is None: raise ValueError('镜头不存在')
        shot=p['shots'][index]
        if 'visual_role' in body:
            c.update_shot_visual_role(p,sid,body['visual_role'])
            shot=p['shots'][index]
        elif 'kind' in body:
            role='A' if str(body['kind']).upper()=='A' else 'E'
            c.update_shot_visual_role(p,sid,role)
            shot=p['shots'][index]
        evidence_inputs=('evidence_target','search_query','evidence_url','evidence_focus','evidence_crop','evidence_zoom')
        before_evidence={key:json.loads(json.dumps(shot.get(key))) for key in evidence_inputs}
        for key in ('title','reason','keywords','media_start'):
            if key in body: shot[key]=body[key]
        for key,limit in (
            ('evidence_target',240),('search_query',240),('stock_search_query',240),('recording_target',500),
            ('evidence_type',80),('evidence_url',1000),('recording_instruction',500),
            ('generation_model',120),('generation_prompt',1000),('reference_image',1000),('source_url',1000),
        ):
            if key in body:shot[key]=str(body.get(key) or '').strip()[:limit] or None
        for key in ('evidence_focus','evidence_crop','motion_data'):
            if key in body:
                value=body.get(key)
                if value is not None and not isinstance(value,dict):raise ValueError(f'{key} 必须是对象')
                shot[key]=value or {}
        if 'evidence_zoom' in body:
            try:zoom=float(body.get('evidence_zoom') or 1.05)
            except (TypeError,ValueError):raise ValueError('证据缩放参数无效') from None
            if not 1.0<=zoom<=1.35:raise ValueError('证据缩放需在 1.0 到 1.35 之间')
            shot['evidence_zoom']=round(zoom,3)
        if 'stock_search_query_alt' in body:
            raw=body.get('stock_search_query_alt')
            if not isinstance(raw,list):raise ValueError('B 类备选搜索词必须是数组')
            shot['stock_search_query_alt']=[
                str(value).strip()[:240] for value in raw[:3] if str(value).strip()
            ]
        if 'reference_images' in body:
            raw=body.get('reference_images')
            if not isinstance(raw,list):raise ValueError('G 类参考图必须是数组')
            shot['reference_images']=[
                str(value).strip()[:1000] for value in raw[:9] if str(value).strip()
            ]
            shot['reference_image']=shot['reference_images'][0] if shot['reference_images'] else None
        if 'reference_audios' in body:
            raw=body.get('reference_audios')
            if not isinstance(raw,list):raise ValueError('G 类参考音频必须是数组')
            shot['reference_audios']=[
                str(value).strip()[:1000] for value in raw[:3] if str(value).strip()
            ]
        if 'motion_type' in body:
            from visual_director.schema import MOTION_TYPES
            motion_type=str(body.get('motion_type') or '').strip().upper()
            if motion_type and motion_type not in MOTION_TYPES:raise ValueError('请选择支持的 Motion 模板')
            shot['motion_type']=motion_type or None
        query=shot.get('stock_search_query') or shot.get('search_query')
        if query and not shot.get('keywords'):
            shot['keywords']=[str(query)[:100]]
        segment_id=shot.get('visual_segment_id')
        segment=next((item for item in (p.get('visual_master_plan') or {}).get('segments',[]) if item.get('id')==segment_id),None)
        if segment:
            for key in (
                'evidence_target','search_query','recording_target','recording_instruction',
                'stock_search_query','stock_search_query_alt','generation_model','generation_prompt',
                'reference_image','source_url','motion_type','motion_data','evidence_type',
                'reference_images','reference_audios','evidence_url','evidence_focus','evidence_crop','evidence_zoom',
            ):
                if key in body:segment[key]=shot.get(key)
        from visual_director.router import refresh_shot_route
        refresh_shot_route(p,shot)
        if any(before_evidence[key]!=shot.get(key) for key in evidence_inputs):
            # The screenshot on disk was captured for the previous inputs, so
            # keep the edit from silently reusing it on the next resolve.
            shot.update(asset=None,source=None,candidates=[],media_start=0,
                        material_status='pending',material_error=None)
        if 'aroll_config' in body:
            raw=body['aroll_config'] if isinstance(body['aroll_config'],dict) else {}
            provider=str(raw.get('provider') or 'global')
            if provider not in ('global','musetalk','latentsync','wav2lip','infinitetalk','autodl_h3','custom'):
                raise ValueError('请选择支持的 A-roll 生成工具')
            resolution=str(raw.get('resolution') or '')
            if resolution and resolution not in ('480p竖','768p竖','1080p竖','480p横','768p横','1080p横'):
                raise ValueError('请选择支持的 A-roll 分辨率')
            batch_size=int(raw.get('batch_size') or 0)
            if batch_size and batch_size not in (1,2,4,8,16):raise ValueError('请选择支持的显存档位')
            positive_prompt=str(raw.get('positive_prompt') or '').strip()
            negative_prompt=str(raw.get('negative_prompt') or '').strip()
            if len(positive_prompt)>4000 or len(negative_prompt)>4000:raise ValueError('单镜头提示词不能超过 4000 个字符')
            shot['aroll_config']={'provider':provider,'resolution':resolution,'batch_size':batch_size}
            if positive_prompt:shot['aroll_config']['positive_prompt']=positive_prompt
            if negative_prompt:shot['aroll_config']['negative_prompt']=negative_prompt
        if shot['kind'] not in ('A','B'): raise ValueError('镜头类型无效')
        if not isinstance(shot['keywords'],list) or len(shot['keywords'])>5: raise ValueError('最多 5 个检索词')
        shot['keywords']=[str(k)[:100] for k in shot['keywords']]; shot['title']=str(shot['title'])[:100]; shot['reason']=str(shot['reason'])[:1000]
        shot['media_start']=float(shot['media_start'])
        if not math.isfinite(shot['media_start']) or shot['media_start']<0: raise ValueError('素材入点无效')
        if shot.get('asset') and Path(shot['asset']).suffix=='.mp4' and shot['media_start']>=c.probe(c.asset_path(pid,shot['asset']))['duration']: raise ValueError('素材入点超过视频时长')
        if 'end' in body:
            if index==len(p['shots'])-1: raise ValueError('最后一个镜头必须结束于音频结尾')
            end=float(body['end']); shot['end']=end; p['shots'][index+1]['start']=end
        c.validate_timeline(p['shots'],p['duration'])
        p['revision']+=1; c.save_project(p); return p

@app.post('/api/projects/{pid}/shots/{sid}/split')
def split_shot(pid:str,sid:str,body:dict):
    with c.LOCK:
        c.ensure_idle(pid);p=c.read_project(pid)
        result=c.split_shot_semantically(p,sid,body.get('time'))
        p['revision']+=1;c.save_project(p)
        return result

@app.post('/api/projects/{pid}/shots/{sid}/merge')
def merge_shot(pid:str,sid:str,body:dict):
    direction=str(body.get('direction') or 'next')
    if direction not in ('previous','next'):raise ValueError('合并方向无效')
    with c.LOCK:
        c.ensure_idle(pid);p=c.read_project(pid)
        result=c.merge_shots_semantically(p,sid,direction)
        p['revision']+=1;c.save_project(p)
        return result

@app.post('/api/projects/{pid}/shots/{sid}/search')
def search(pid:str,sid:str):
    with operation(pid,'搜索候选素材','materials'):
        p=c.read_project(pid); shot=next((s for s in p['shots'] if s['id']==sid),None)
        if not shot: raise ValueError('镜头不存在')
        if shot.get('visual_role')=='E' or shot.get('evidence_required'):
            raise ValueError('这一镜需要真实证据；请导入官方截图 / 现有素材，程序不会用泛素材替代')
        found=[]; seen=set()
        terms=[*(shot.get('keywords') or [])[:3]]
        query=shot.get('stock_search_query') or shot.get('search_query')
        if query and query not in terms:terms.insert(0,query)
        for term in terms[:3]:
            source=resolve_broll_config(c.settings(True),require_key=True)['provider']
            for cand in c.search_stock(term,source,c.settings(True),p.get('options')):
                if cand['id'] not in seen: found.append(cand); seen.add(cand['id'])
            if len(found)>=c.CANDIDATE_LIMIT: break
        shot['candidates']=c.stash_candidates(pid,sid,found[:c.CANDIDATE_LIMIT]); c.save_project(p); return p

@app.post('/api/projects/{pid}/shots/{sid}/select')
def select(pid:str,sid:str,body:dict):
    with operation(pid,'下载所选素材','materials'):
        candidate=c.get_candidate(pid,sid,str(body.get('candidate_id','')))
        p=c.read_project(pid); shot=next((s for s in p['shots'] if s['id']==sid),None)
        if not shot: raise ValueError('镜头不存在')
        if shot.get('visual_role')=='E':raise ValueError('真实证据镜头不能使用普通库存素材')
        expected=p.get('options',{}).get('aspect_ratio','16:9')
        if candidate.get('target_aspect_ratio','16:9')!=expected:
            raise ValueError('候选素材属于其他画幅，请按当前画幅重新搜索')
        asset=c.download_candidate(pid,candidate)
        shot.update(kind='B',asset=asset,source={k:v for k,v in candidate.items() if k!='download_url'},media_start=0,material_status='ready',material_error=None)
        p['revision']+=1; c.save_project(p); return p


@app.post('/api/projects/{pid}/shots/{sid}/resolve')
def resolve_visual(pid:str,sid:str):
    with operation(pid,'重新解析视觉素材','materials'):
        c.materials(pid,sid)
        return c.read_project(pid)

@app.get('/api/projects/{pid}/files/{name:path}')
def files(pid:str,name:str):
    # Only media and export artifacts are public. Credentials and project internals are excluded.
    if not (name.startswith('assets/') or name.startswith('exports/')): raise HTTPException(404)
    path=c.asset_path(pid,name)
    if path.suffix.lower() not in ('.jpg','.png','.webp','.mp4','.mp3','.wav','.m4a','.ogg','.flac','.aac','.srt','.json','.zip'): raise HTTPException(404)
    return FileResponse(path)

@app.get('/api/projects/{pid}/subtitles')
def subtitles(pid:str):
    p=c.read_project(pid); path=c.project_dir(pid)/'exports/transcript.srt'; c.write_srt(p,path)
    return FileResponse(path,filename='字幕.srt')

app.mount('/',StaticFiles(directory=str(c.ROOT/'static'),html=True),name='static')

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('SOLO_PORT','8766')),log_level='info')
