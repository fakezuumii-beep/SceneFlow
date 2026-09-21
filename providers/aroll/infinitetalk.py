"""Single-speaker InfiniteTalk through the user's existing ComfyUI server."""
from __future__ import annotations
import copy, hashlib, json, math, time, uuid
import requests
from .comfyui import ComfyUIProvider


class InfiniteTalkProvider(ComfyUIProvider):
    id='infinitetalk'
    name='InfiniteTalk 单人 Q8'
    short_name='InfiniteTalk · 单人'
    runtime='comfyui'
    version='infinitetalk-single-provider-v4'
    PORTRAIT_SIZE=(480,832)

    @staticmethod
    def _prompt_nodes(graph):
        return [node for node in graph.values()
                if isinstance(node.get('inputs',{}).get('positive_prompt'),str)
                and isinstance(node.get('inputs',{}).get('negative_prompt'),str)]

    def prompt_defaults(self,graph=None):
        nodes=self._prompt_nodes(graph or self.workflow())
        if not nodes:return None
        positive={node['inputs']['positive_prompt'] for node in nodes}
        negative={node['inputs']['negative_prompt'] for node in nodes}
        if len(positive)!=1 or len(negative)!=1:
            raise ValueError('InfiniteTalk 工作流包含多组不同提示词，无法安全映射到统一输入框')
        return {'positive_prompt':positive.pop(),'negative_prompt':negative.pop()}

    def effective_prompts(self,graph=None):
        defaults=self.prompt_defaults(graph)
        if not defaults:return None
        return {
            'positive_prompt':str(self.settings.get('aroll_infinitetalk_positive_prompt') or '').strip() or defaults['positive_prompt'],
            'negative_prompt':str(self.settings.get('aroll_infinitetalk_negative_prompt') or '').strip() or defaults['negative_prompt'],
        }

    @staticmethod
    def run_config_key(shot):
        config=shot.get('aroll_config') or {}
        provider=str(config.get('provider') or 'global')
        if provider in ('global','infinitetalk'):provider='infinitetalk'
        return (provider,str(config.get('positive_prompt') or '').strip(),str(config.get('negative_prompt') or '').strip())

    @staticmethod
    def _integer_input(graph,node,name):
        value=node.get('inputs',{}).get(name)
        if isinstance(value,(int,float)) and not isinstance(value,bool):return int(value)
        if isinstance(value,list) and len(value)>=2:
            source=graph.get(str(value[0]),{})
            raw=source.get('inputs',{}).get('value')
            if source.get('class_type') in ('INTConstant','PrimitiveInt','Int') and isinstance(raw,(int,float)):
                return int(raw)
        return None

    @staticmethod
    def _set_integer_input(graph,node,name,value):
        current=node.get('inputs',{}).get(name)
        if isinstance(current,(int,float)) and not isinstance(current,bool):
            node['inputs'][name]=int(value);return True
        if isinstance(current,list) and len(current)>=2:
            source=graph.get(str(current[0]),{})
            raw=source.get('inputs',{}).get('value')
            if source.get('class_type') in ('INTConstant','PrimitiveInt','Int') and isinstance(raw,(int,float)):
                source['inputs']['value']=int(value);return True
        return False

    def apply_aspect_ratio(self,graph,aspect_ratio):
        """Adapt the imported host resize for native square or portrait inference."""
        if aspect_ratio not in ('1:1','9:16'):return None
        person=str(self.settings['aroll_person_node']);changed=[]
        for node in graph.values():
            image=node.get('inputs',{}).get('image')
            if ('ImageResize' not in str(node.get('class_type','')) or not isinstance(image,list)
                    or str(image[0])!=person):continue
            width=self._integer_input(graph,node,'width');height=self._integer_input(graph,node,'height')
            if not width or not height:continue
            target=(min(width,height),)*2 if aspect_ratio=='1:1' else self.PORTRAIT_SIZE
            if self._set_integer_input(graph,node,'width',target[0]) and self._set_integer_input(graph,node,'height',target[1]):
                changed.append(target)
        if not changed:
            raise ValueError(f'当前 InfiniteTalk 工作流无法自动切换为 {aspect_ratio}；人物输入后需要可设置宽高的 ImageResize 节点')
        return changed[0]

    def workflow(self):
        import core as c
        path=(c.PRIVATE/str(self.settings.get('aroll_comfyui_workflow') or '')).resolve()
        if not path.is_relative_to(c.PRIVATE.resolve()) or not path.is_file():raise ValueError('请导入单人 InfiniteTalk API 工作流')
        graph=json.loads(path.read_text(encoding='utf-8-sig'))
        if not isinstance(graph,dict) or not graph or any(not isinstance(n,dict) or 'class_type' not in n or not isinstance(n.get('inputs'),dict) for n in graph.values()):
            raise ValueError('请导入 API 格式工作流，不能使用画布 JSON')
        return graph

    def validate_config(self):
        super().validate_config();graph=self.workflow()
        for key,expected in (('aroll_person_node','LoadImage'),('aroll_audio_node','LoadAudio'),('aroll_output_node','VHS_VideoCombine')):
            if graph.get(str(self.settings[key]),{}).get('class_type')!=expected:raise ValueError(f'{key} 必须指向 {expected}')
        embeds=[n for n in graph.values() if n['class_type']=='MultiTalkWav2VecEmbeds']
        if len(embeds)!=1 or any(k in embeds[0]['inputs'] for k in ('audio_2','audio_3','audio_4')):raise ValueError('需要仅连接一条音轨的 InfiniteTalk 工作流')
        return True

    def request(self,method,path,**kwargs):
        try:
            result=requests.request(method,str(self.settings['aroll_comfyui_url']).rstrip('/')+path,timeout=(5,30),**kwargs)
            result.raise_for_status();return result
        except requests.RequestException as exc:
            detail=exc.response.text[:1200] if exc.response is not None else '请确认 ComfyUI 已启动'
            raise ValueError('ComfyUI 请求失败：'+detail) from exc

    def status(self,check_online=False):
        try:
            self.validate_config()
            if check_online:self.test_connection()
        except (ValueError,OSError) as exc:return {'ready':False,'installed':False,'message':str(exc)}
        return {'ready':True,'installed':True,'configured':True,'message':'单人 Q8 · 图片驱动 · 25fps · '+('连接已验证' if check_online else '生成时检查连接')}

    def test_connection(self):
        self.validate_config();self.request('GET','/system_stats')
        schema=self.request('GET','/object_info').json()
        for key,node in self.workflow().items():
            if node['class_type'] not in schema:raise ValueError(f"ComfyUI 缺少节点：{node['class_type']}")
            spec=schema[node['class_type']]['input']
            for name,value in node['inputs'].items():
                rule=spec.get('required',{}).get(name,spec.get('optional',{}).get(name))
                if rule and isinstance(rule[0],list) and not isinstance(value,list) and value not in rule[0] and name not in ('image','audio'):
                    raise ValueError(f'节点 {key} 的 {name} 不可用：{value}')
        return {'ok':True,'message':'InfiniteTalk 连接、节点和模型配置已验证'}

    def cache_identity(self):
        defaults=effective=None
        try:
            graph=self.workflow();digest=self.workflow_hash(graph);defaults=self.prompt_defaults(graph);effective=self.effective_prompts(graph)
        except (ValueError,OSError):digest=self.settings.get('aroll_comfyui_workflow_hash')
        identity={**super().cache_identity(),'workflow_hash':digest,'model':'InfiniteTalk Single Q8',
                  'endpoint':self.settings.get('aroll_comfyui_url')}
        if defaults and effective and effective!=defaults:
            identity['prompt_override_hash']=hashlib.sha256(json.dumps(effective,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16]
        return identity

    def project_cache_identity(self,project):
        identity=self.cache_identity()
        aspect_ratio=project.get('options',{}).get('aspect_ratio','16:9')
        if aspect_ratio=='1:1':
            identity={**identity,'aspect_ratio':'1:1','square_strategy':'short-side-v1'}
        elif aspect_ratio=='9:16':
            identity={**identity,'aspect_ratio':'9:16','portrait_strategy':'480x832-v1'}
        return identity

    def signature(self,project,shot):
        import aroll
        return aroll.signature(project,shot,self.project_cache_identity(project),self.run_config_key)

    def upload(self,path):
        with path.open('rb') as stream:
            value=self.request('POST','/upload/image',files={'image':(path.name,stream)},data={'type':'input','overwrite':'false'}).json()
        return '/'.join(x for x in (value.get('subfolder'),value['name']) if x)

    def build_prompt(self,image,audio,frames,prefix,aspect_ratio='16:9'):
        if not 1<=frames<=10000:raise ValueError('单个连续 A-roll 超过 InfiniteTalk 的 10000 帧上限，请拆分长段落')
        graph=copy.deepcopy(self.workflow())
        self.apply_aspect_ratio(graph,aspect_ratio)
        graph[str(self.settings['aroll_person_node'])]['inputs']['image']=image
        graph[str(self.settings['aroll_audio_node'])]['inputs']['audio']=audio
        graph[str(self.settings['aroll_output_node'])]['inputs'].update(frame_rate=25,filename_prefix=prefix,save_output=True,format='video/h264-mp4',pingpong=False,loop_count=0)
        prompts=self.effective_prompts(graph)
        if prompts:
            for node in self._prompt_nodes(graph):node['inputs'].update(prompts)
        for node in graph.values():
            if node['class_type']=='MultiTalkWav2VecEmbeds':node['inputs'].update(num_frames=frames,fps=25.0)
        return graph

    def collect(self,pid,cache,prompt):
        import core as c
        raw=cache/'raw.mp4';jobfile=cache/'comfy-job.json'
        if jobfile.is_file():job=json.loads(jobfile.read_text(encoding='utf-8'))
        else:
            c.atomic_json(jobfile,{'prompt_id':None,'state':'submitting'})
            result=self.request('POST','/prompt',json={'prompt':prompt,'client_id':'solo-'+pid}).json()
            if result.get('node_errors'):raise ValueError('工作流校验失败：'+str(result['node_errors']))
            job={'prompt_id':result['prompt_id']};c.atomic_json(jobfile,job)
        prompt_id=job.get('prompt_id')
        if not prompt_id:raise ValueError('上次提交结果不明确，请检查 ComfyUI 队列后重新生成这一镜，避免重复提交')
        began=time.monotonic()
        while True:
            if c.ACTIVE.get(pid,{}).get('cancel'):
                self.request('POST','/queue',json={'delete':[prompt_id]})
                raise RuntimeError('工作台已停止；ComfyUI 若已开始推理，结果会保留供下次继续取回')
            history=self.request('GET','/history/'+prompt_id).json().get(prompt_id)
            if history:
                if history.get('status',{}).get('status_str')=='error':
                    jobfile.unlink(missing_ok=True)
                    raise RuntimeError('InfiniteTalk 推理失败：'+str(history['status'].get('messages',[]))[-1500:])
                output=history.get('outputs',{}).get(str(self.settings['aroll_output_node']),{})
                videos=[x for group in ('gifs','videos','images') for x in output.get(group,[]) if x.get('filename','').lower().endswith('.mp4')]
                if videos:
                    item=videos[-1];temp=raw.with_suffix('.download.mp4')
                    with self.request('GET','/view',params={k:item.get(k,'') for k in ('filename','subfolder','type')},stream=True) as response,temp.open('wb') as stream:
                        for chunk in response.iter_content(1024*1024):stream.write(chunk)
                    c.probe(temp);c.run([c.FFMPEG,'-v','error','-i',temp,'-map','0:v:0','-f','null','-'],timeout=600)
                    temp.replace(raw);c.atomic_json(cache/'comfy-history.json',history);return raw
                if history.get('status',{}).get('completed'):raise RuntimeError('InfiniteTalk 输出节点没有返回 MP4')
            queue=self.request('GET','/queue').json()
            if not history and not any(x[1]==prompt_id for key in ('queue_running','queue_pending') for x in queue.get(key,[])):
                jobfile.unlink(missing_ok=True);raise RuntimeError('ComfyUI 任务已不在队列或历史中，请重试')
            elapsed=int(time.monotonic()-began)
            c.progress(pid,'InfiniteTalk 生成',10,f'等待人物视频 · {elapsed//60} 分 {elapsed%60} 秒')
            if elapsed>12*3600:raise RuntimeError('等待超时；任务编号已保存，可继续取回结果')
            time.sleep(2)

    def generate(self,pid,shot_id=None):
        import core as c
        import aroll
        p=c.read_project(pid);aspect_ratio=p.get('options',{}).get('aspect_ratio','16:9')
        identity=self.project_cache_identity(p);folder=c.project_dir(pid);runs=aroll.contiguous_runs(p['shots'],self.run_config_key)
        if shot_id and not any(s['id']==shot_id for run in runs for s in run):raise ValueError('未找到 A-roll 镜头')
        pending=[run for run in runs if (any(s['id']==shot_id for s in run) if shot_id else any(not self.is_ready(p,s) for s in run))]
        if not pending:return
        self.test_connection();c.validate_timeline(p['shots'],p['duration'])
        for index,run in enumerate(pending):
            if c.ACTIVE.get(pid,{}).get('cancel'):raise RuntimeError('已停止')
            key=aroll.run_signature(p,run,identity)+('-'+uuid.uuid4().hex[:8] if shot_id else '')
            cache=folder/'aroll-cache'/('infinitetalk-'+key);cache.mkdir(parents=True,exist_ok=True)
            start=max(0,float(run[0]['start'])-aroll.CONTEXT);end=min(p['duration'],float(run[-1]['end'])+aroll.CONTEXT)
            audio=cache/('audio-'+key+'.wav');image=cache/('host-'+key+'.png')
            # InfiniteTalk can return one fewer frame at an exact audio boundary.
            # A short silent tail gives the decoder enough real generated frames to trim cleanly.
            tail=.12
            c.run([c.FFMPEG,'-y','-v','error','-ss',str(start),'-i',c.asset_path(pid,p['audio']),
                   '-af',f'apad=pad_dur={tail}','-t',str(end-start+tail),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',audio])
            c.run([c.FFMPEG,'-y','-v','error','-i',c.host_image(p),'-frames:v','1',image])
            raw=cache/'raw.mp4'
            if not raw.is_file():
                promptfile=cache/'prompt.json'
                if promptfile.is_file():prompt=json.loads(promptfile.read_text(encoding='utf-8'))
                else:
                    prompt=self.build_prompt(self.upload(image),self.upload(audio),math.ceil((end-start)*25)+1,'SOLO/'+pid+'/'+key,aspect_ratio)
                    c.atomic_json(promptfile,prompt)
                raw=self.collect(pid,cache,prompt)
            first=round((float(run[0]['start'])-start)*25);last=round((float(run[-1]['end'])-start)*25)
            video=next(x for x in c.probe(raw)['streams'] if x['codec_type']=='video')
            if aspect_ratio=='1:1' and int(video['width'])!=int(video['height']):
                raise RuntimeError('InfiniteTalk 返回的不是 1:1 视频；请检查工作流的人物缩放节点')
            if aspect_ratio=='9:16' and int(video['width'])>=int(video['height']):
                raise RuntimeError('InfiniteTalk 返回的不是竖屏视频；请检查工作流的人物缩放节点')
            if int(video.get('nb_frames',0))<last:
                # Window stitching can drop two tail frames even when the requested count is long enough.
                # Retry only this failed run with a larger silent tail; completed runs keep their cache.
                retry_frames=last+4;retry=cache/f'extend-{retry_frames}';retry.mkdir(exist_ok=True)
                retry_audio=retry/('audio-'+key+'.wav')
                c.run([c.FFMPEG,'-y','-v','error','-ss',str(start),'-i',c.asset_path(pid,p['audio']),
                       '-af','apad=pad_dur=0.36','-t',str(end-start+.36),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',retry_audio])
                prompt=self.build_prompt(self.upload(image),self.upload(retry_audio),retry_frames,'SOLO/'+pid+'/'+key+'-extend',aspect_ratio)
                c.atomic_json(retry/'prompt.json',prompt);raw=self.collect(pid,retry,prompt)
                video=next(x for x in c.probe(raw)['streams'] if x['codec_type']=='video')
                if aspect_ratio=='1:1' and int(video['width'])!=int(video['height']):
                    raise RuntimeError('InfiniteTalk 返回的不是 1:1 视频；请检查工作流的人物缩放节点')
                if aspect_ratio=='9:16' and int(video['width'])>=int(video['height']):
                    raise RuntimeError('InfiniteTalk 返回的不是竖屏视频；请检查工作流的人物缩放节点')
            rate=video.get('avg_frame_rate','0/1').split('/')
            if abs(float(rate[0])/float(rate[1])-25)>.01:raise RuntimeError('InfiniteTalk 输出帧率不是 25fps')
            if int(video.get('nb_frames',0))<last:raise RuntimeError('人物视频短于镜头；已保留结果，不会循环或冻结补齐')
            asset=folder/'assets'/('aroll-run-infinitetalk-'+key+'.mp4');temp=asset.with_suffix('.part.mp4')
            c.run([c.FFMPEG,'-y','-v','error','-i',raw,'-an','-vf',f'trim=start_frame={first}:end_frame={last},setpts=PTS-STARTPTS','-c:v','libx264','-crf','16','-preset','medium','-pix_fmt','yuv420p','-movflags','+faststart',temp])
            if not aroll.valid_chunk(temp,last-first):raise RuntimeError('A-roll 帧数校验失败')
            temp.replace(asset)
            with c.LOCK:
                current=c.read_project(pid)
                for s in run:
                    target=next(x for x in current['shots'] if x['id']==s['id'])
                    if self.signature(current,target)!=self.signature(p,s):raise RuntimeError('生成期间输入已变化，结果保留在缓存')
                    if target.get('aroll_asset'):target.setdefault('aroll_history',[]).append({'asset':target['aroll_asset'],'signature':target.get('aroll_signature')})
                    target.update(aroll_asset=asset.relative_to(folder).as_posix(),aroll_signature=self.signature(p,s),aroll_status='ready',aroll_error=None,
                        aroll_media_start=(round((s['start']-start)*25)-first)/25,
                        aroll_provenance={**identity,'engine':self.name,'runtime':self.runtime,'fps':25,'width':video['width'],'height':video['height'],
                            'source':c.host_image(p).relative_to(folder).as_posix(),'source_kind':'image','loop_mode':None,
                            'audio_start':s['start'],'audio_end':s['end'],'continuous_run_start':run[0]['start'],'continuous_run_end':run[-1]['end']})
                current['revision']+=1;c.save_project(current)
            c.progress(pid,'InfiniteTalk 生成',99*(index+1)/len(pending),f'已完成连续人物片段 {index+1}/{len(pending)}')
