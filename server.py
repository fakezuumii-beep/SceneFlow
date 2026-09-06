from __future__ import annotations
import copy, json, math, mimetypes, os, re, shutil, time, uuid
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from PIL import Image, ImageOps
import core as c
import aroll
LOADED_REVISION=c.code_revision()

@asynccontextmanager
async def lifespan(app):
    c.recover_jobs()
    yield

app=FastAPI(title='SOLO 单人播客工作台',docs_url='/api/docs',lifespan=lifespan)
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

@app.get('/api/health')
def health():
    return {'status':'ok','revision':LOADED_REVISION,'update_required':LOADED_REVISION!=c.code_revision(),
            'features':{'reliable_planning':True,'semantic_rule_planning':True,'musetalk':True,'direct_musetalk':True,'deepseek_api':True,'text_to_video':True}}

@app.get('/api/local-models')
def local_models():
    import local_engines
    return local_engines.status()

@app.put('/api/projects/{pid}/script')
def save_script(pid:str,body:dict):
    import local_engines
    script=local_engines.validate_script(body)
    with c.LOCK:
        c.ensure_idle(pid);p=c.read_project(pid)
        if p.get('script')!=script:
            p['script']=script;p['revision']+=1;c.save_project(p)
        return p

@app.get('/api/aroll/status')
def aroll_status():return aroll.installation_status(True)

@app.put('/api/settings')
def put_settings(body:dict):
    with c.LOCK:
        if c.ACTIVE: raise ValueError('任务运行中，请完成后再修改连接设置')
        return c.save_settings(body)

@app.get('/api/projects')
def projects():
    result=[]
    for path in c.PROJECTS.glob('*/project.json'):
        p=c.read_project(path.parent.name)
        result.append({k:p.get(k) for k in ('id','name','duration','updated_at','job')})
    return sorted(result,key=lambda p:p['updated_at'],reverse=True)

@app.post('/api/projects')
def create(body:dict): return c.create_project(str(body.get('name','我的第一期播客')))

@app.get('/api/projects/{pid}')
def project(pid:str):
    p=c.read_project(pid); p['captions']=c.subtitle_events(p); return aroll.decorate(p)

@app.patch('/api/projects/{pid}')
def patch_project(pid:str,body:dict):
    with c.LOCK:
        c.ensure_idle(pid); p=c.read_project(pid)
        if 'name' in body: p['name']=str(body['name']).strip()[:120] or '未命名播客'
        if 'options' in body:
            options={**p['options'],**body['options']}
            options={k:options[k] for k in p['options']}
            if options['resolution'] not in ('720p','1080p') or options['source'] not in ('pexels','pixabay'): raise ValueError('设置选项无效')
            if not 0<=int(options['broll_ratio'])<=80 or not 6<=int(options['max_shot'])<=40: raise ValueError('分镜偏好超出范围')
            options['broll_ratio']=int(options['broll_ratio']); options['max_shot']=int(options['max_shot']); options['subtitles']=bool(options['subtitles'])
            p['options']=options
        p['revision']+=1; c.save_project(p); return p

@app.post('/api/projects/{pid}/upload')
def upload(pid:str,kind:str=Form(...),file:UploadFile=File(...),shot_id:str=Form('')):
    with operation(pid,'导入素材'):
        p=c.read_project(pid); folder=c.project_dir(pid)
        ext=Path(file.filename or '').suffix.lower()
        if kind=='audio': allowed={'.mp3','.wav','.m4a','.aac','.flac','.ogg','.mp4','.webm'}
        elif kind=='portrait': allowed={'.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv','.webm','.m4v'}
        elif kind=='broll': allowed={'.mp4','.mov','.mkv','.webm','.m4v','.png','.jpg','.jpeg','.webp'}
        elif kind=='srt': allowed={'.srt'}
        else: raise ValueError('不支持的素材类型')
        if ext not in allowed: raise ValueError('文件格式不支持')
        token=uuid.uuid4().hex[:12]; target=folder/'assets'/f'{kind}-{token}{ext}'
        size=0
        try:
            with target.open('wb') as f:
                while chunk:=file.file.read(1024*1024):
                    size+=len(chunk)
                    if size>2*1024**3: raise ValueError('文件超过 2 GB')
                    f.write(chunk)
            if kind=='audio':
                info=c.probe(target)
                if not any(s['codec_type']=='audio' for s in info['streams']) or info['duration']<=0: raise ValueError('没有找到有效音轨')
                if info['duration']>4*3600: raise ValueError('第一版支持最长 4 小时音频')
                # Browser and renderer use the same normalized PCM master, with no content edits.
                audio=target.with_suffix('.master.wav')
                c.run([c.FFMPEG,'-y','-v','error','-i',target,'-vn','-ac','2','-ar','48000','-c:a','pcm_s16le',audio],timeout=1800)
                p.update(audio=str(audio.relative_to(folder)).replace('\\','/'),audio_name=file.filename,
                         duration=round(c.probe(audio)['duration'],3),segments=[],candidate_segments=[],narrative_segments=[],shots=[],analysis=None,waveform=c.waveform(audio))
                p.pop('script',None);p.pop('tts',None)
            elif kind in ('portrait','broll'):
                is_image=ext in ('.png','.jpg','.jpeg','.webp')
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
                if kind=='portrait':
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
    folder=c.ROOT/'我的素材'
    return [{'name':path.name} for path in sorted(folder.iterdir()) if path.is_file() and
            path.suffix.lower() in ('.png','.jpg','.jpeg','.webp','.mp4','.mov','.mkv','.webm','.m4v')] if folder.is_dir() else []

@app.post('/api/projects/{pid}/host-material')
def use_host_material(pid:str,body:dict):
    name=str(body.get('name',''))
    folder=(c.ROOT/'我的素材').resolve();path=(folder/name).resolve()
    if not name or path.parent!=folder or not path.is_file():raise ValueError('未找到所选人物素材')
    with path.open('rb') as f:
        return upload(pid,kind='portrait',file=UploadFile(file=f,filename=path.name),shot_id='')

@contextmanager
def operation(pid,label):
    with c.LOCK:
        c.ensure_idle(pid)
        if c.ACTIVE: raise ValueError('另一个任务正在处理，请稍后重试')
        p=c.read_project(pid)
        p['job']={'action':label,'stage':label,'status':'running','progress':0,'message':label+'…','started_at':time.time()}; c.save_project(p)
        c.ACTIVE[pid]={'cancel':False}
    try:
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

@app.post('/api/projects/{pid}/cancel')
def cancel(pid:str):
    with c.LOCK:
        if pid in c.ACTIVE: c.ACTIVE[pid]['cancel']=True
    return {'message':'将在当前处理步骤结束后停止，已完成内容会保留'}

@app.patch('/api/projects/{pid}/shots/{sid}')
def patch_shot(pid:str,sid:str,body:dict):
    with c.LOCK:
        c.ensure_idle(pid); p=c.read_project(pid); index=next((i for i,s in enumerate(p['shots']) if s['id']==sid),None)
        if index is None: raise ValueError('镜头不存在')
        shot=p['shots'][index]
        for key in ('kind','title','reason','keywords','media_start'):
            if key in body: shot[key]=body[key]
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

@app.post('/api/projects/{pid}/shots/{sid}/search')
def search(pid:str,sid:str):
    with operation(pid,'搜索候选素材'):
        p=c.read_project(pid); shot=next((s for s in p['shots'] if s['id']==sid),None)
        if not shot: raise ValueError('镜头不存在')
        found=[]; seen=set()
        for term in shot['keywords'][:3]:
            for cand in c.search_stock(term,p['options']['source'],c.settings(True)):
                if cand['id'] not in seen: found.append(cand); seen.add(cand['id'])
            if len(found)>=c.CANDIDATE_LIMIT: break
        shot['candidates']=c.stash_candidates(pid,sid,found[:c.CANDIDATE_LIMIT]); c.save_project(p); return p

@app.post('/api/projects/{pid}/shots/{sid}/select')
def select(pid:str,sid:str,body:dict):
    with operation(pid,'下载所选素材'):
        candidate=c.get_candidate(pid,sid,str(body.get('candidate_id','')))
        asset=c.download_candidate(pid,candidate)
        p=c.read_project(pid); shot=next((s for s in p['shots'] if s['id']==sid),None)
        if not shot: raise ValueError('镜头不存在')
        shot.update(kind='B',asset=asset,source={k:v for k,v in candidate.items() if k!='download_url'},media_start=0,material_status='ready',material_error=None)
        p['revision']+=1; c.save_project(p); return p

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
