import copy, json, math, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from unittest.mock import Mock, patch

class TimelineTests(unittest.TestCase):
    def test_project_output_sizes_include_square_and_portrait(self):
        self.assertEqual(core.output_size({'resolution':'1080p','aspect_ratio':'16:9'}),(1920,1080))
        self.assertEqual(core.output_size({'resolution':'1080p','aspect_ratio':'1:1'}),(1080,1080))
        self.assertEqual(core.output_size({'resolution':'720p','aspect_ratio':'1:1'}),(720,720))
        self.assertEqual(core.output_size({'resolution':'1080p','aspect_ratio':'9:16'}),(1080,1920))
        self.assertEqual(core.output_size({'resolution':'720p','aspect_ratio':'9:16'}),(720,1280))

    def test_legacy_project_options_default_to_landscape(self):
        project={'options':{'resolution':'720p'}}
        self.assertTrue(core.normalize_project_options(project))
        self.assertEqual(project['options']['aspect_ratio'],'16:9')
        self.assertEqual(project['options']['workflow_mode'],'direct')
        self.assertFalse(core.normalize_project_options(project))

    def test_semantic_split_snaps_to_real_boundary_and_merge_restores_timeline(self):
        project={'duration':6.0,
                 'candidate_segments':[{'id':0,'start':0,'end':1.8,'text':'第一句。'},
                                       {'id':1,'start':2,'end':3.8,'text':'第二句。'},
                                       {'id':2,'start':4,'end':6,'text':'第三句。'}],
                 'narrative_segments':[{'id':'n1','start':0,'end':2,'text':'第一句。','semantic_type':'opinion','visual_subject':'观点','visual_value':1,'host_value':4},
                                       {'id':'n2','start':2,'end':4,'text':'第二句。','semantic_type':'process','visual_subject':'过程','visual_value':4,'host_value':2},
                                       {'id':'n3','start':4,'end':6,'text':'第三句。','semantic_type':'data','visual_subject':'数据','visual_value':4,'host_value':3}],
                 'segments':[],
                 'shots':[{'id':'b1','kind':'B','start':0,'end':6,'title':'完整语义','text':'第一句。第二句。第三句。',
                           'reason':'原始分镜','keywords':['完整语义'],'media_start':0,'asset':'assets/original.mp4','source':{'id':'source-1'},'candidates':[{'id':'source-1'}]}]}
        result=core.split_shot_semantically(project,'b1',3.9)
        self.assertEqual(result['split_time'],4.0)
        self.assertEqual([(s['start'],s['end']) for s in project['shots']],[(0,4.0),(4.0,6)])
        self.assertEqual(project['shots'][0]['text'],'第一句。第二句。')
        self.assertEqual(project['shots'][1]['text'],'第三句。')
        self.assertEqual(project['shots'][0]['asset'],'assets/original.mp4')
        self.assertIsNone(project['shots'][1]['asset'])
        core.merge_shots_semantically(project,result['selected_id'],'previous')
        self.assertEqual(len(project['shots']),1)
        self.assertEqual((project['shots'][0]['start'],project['shots'][0]['end']),(0,6.0))
        self.assertEqual(project['shots'][0]['text'],'第一句。第二句。第三句。')

    def test_semantic_merge_rejects_mixed_visual_kinds(self):
        project={'duration':2,'candidate_segments':[],'narrative_segments':[],'segments':[],
                 'shots':[{'id':'a','kind':'A','start':0,'end':1,'text':'A','title':'A','reason':'','keywords':[],'media_start':0},
                          {'id':'b','kind':'B','start':1,'end':2,'text':'B','title':'B','reason':'','keywords':[],'media_start':0}]}
        with self.assertRaisesRegex(ValueError,'类型不同'):
            core.merge_shots_semantically(project,'a','next')

    def test_semantic_aroll_merge_preserves_history_and_requires_matching_settings(self):
        base={'duration':2,'candidate_segments':[],'narrative_segments':[],'segments':[],
              'shots':[{'id':'a1','kind':'A','start':0,'end':1,'text':'前句','title':'前句','reason':'','keywords':[],'media_start':0,
                        'aroll_config':{'provider':'autodl_h3'},'aroll_asset':'assets/a1.mp4','aroll_signature':'sig1'},
                       {'id':'a2','kind':'A','start':1,'end':2,'text':'后句','title':'后句','reason':'','keywords':[],'media_start':0,
                        'aroll_config':{'provider':'autodl_h3'},'aroll_asset':'assets/a2.mp4','aroll_signature':'sig2'}]}
        project=copy.deepcopy(base);core.merge_shots_semantically(project,'a1','next')
        self.assertNotIn('aroll_asset',project['shots'][0])
        self.assertEqual({item['asset'] for item in project['shots'][0]['aroll_history']},{'assets/a1.mp4','assets/a2.mp4'})
        project=copy.deepcopy(base);project['shots'][1]['aroll_config']={'provider':'infinitetalk'}
        with self.assertRaisesRegex(ValueError,'生成设置不同'):
            core.merge_shots_semantically(project,'a1','next')

    def test_two_step_draft_renders_reference_image_without_aroll(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core,'PROJECTS',Path(directory)):
            project=core.create_project('two-step-draft');folder=core.project_dir(project['id'])
            image=folder/'assets'/'host.jpg';core.Image.new('RGB',(96,54),'#315747').save(image)
            aroll=folder/'assets'/'old-aroll.jpg';core.Image.new('RGB',(96,54),'#a34141').save(aroll)
            audio=folder/'assets'/'audio.wav'
            core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.4','-ar','16000','-ac','1',audio])
            project.update(audio='assets/audio.wav',portrait='assets/host.jpg',portrait_kind='image',duration=.4,
                           job={'status':'running','stage':'test','progress':0,'message':''},
                           shots=[{'id':'a1','kind':'A','start':0,'end':.4,'title':'host','text':'test','camera':'medium',
                                   'aroll_asset':'assets/old-aroll.jpg'}])
            project['options'].update(workflow_mode='two_step',resolution='720p',subtitles=False)
            provider=Mock();provider.is_ready.return_value=True
            core.save_project(project)
            with patch('providers.aroll.get_shot_aroll_provider',return_value=provider):
                core.render(project['id'],allow_aroll_placeholder=True,export_kind='draft')
            saved=core.read_project(project['id']);export=saved['exports'][-1]
            self.assertEqual(export['kind'],'draft');self.assertEqual(export['aroll_placeholders'],1)
            self.assertTrue(export['file'].endswith('/rough-cut.mp4'))
            self.assertTrue((folder/export['file']).is_file())
            manifest=json.loads((folder/Path(export['file']).parent/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['actual_visuals'][0]['visual'],'assets/host.jpg')

    def test_square_project_renders_a_real_square_mp4(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core,'PROJECTS',Path(directory)):
            project=core.create_project('square-render');folder=core.project_dir(project['id'])
            image=folder/'assets'/'visual.jpg';core.Image.new('RGB',(96,54),'#315747').save(image)
            audio=folder/'assets'/'audio.wav'
            core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.4',
                      '-ar','16000','-ac','1',audio])
            project.update(audio='assets/audio.wav',portrait='assets/visual.jpg',portrait_kind='image',duration=.4,
                           job={'status':'running','stage':'test','progress':0,'message':''},
                           shots=[{'id':'b1','kind':'B','start':0,'end':.4,'asset':'assets/visual.jpg','media_start':0,
                                   'visual_change':'cut','source':{'provider':'test'}}])
            project['options'].update(aspect_ratio='1:1',resolution='720p',subtitles=False)
            core.save_project(project);core.render(project['id'])
            result=core.read_project(project['id']);output=folder/result['exports'][-1]['file']
            video=next(s for s in core.probe(output)['streams'] if s['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(720,720))

    def test_portrait_project_renders_a_real_vertical_mp4(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core,'PROJECTS',Path(directory)):
            project=core.create_project('portrait-render');folder=core.project_dir(project['id'])
            image=folder/'assets'/'visual.jpg';core.Image.new('RGB',(54,96),'#315747').save(image)
            audio=folder/'assets'/'audio.wav'
            core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.4',
                      '-ar','16000','-ac','1',audio])
            project.update(audio='assets/audio.wav',portrait='assets/visual.jpg',portrait_kind='image',duration=.4,
                           segments=[{'start':0,'end':.4,'text':'竖屏字幕'}],
                           job={'status':'running','stage':'test','progress':0,'message':''},
                           shots=[{'id':'b1','kind':'B','start':0,'end':.4,'asset':'assets/visual.jpg','media_start':0,
                                   'visual_change':'cut','source':{'provider':'test'}}])
            project['options'].update(aspect_ratio='9:16',resolution='720p',subtitles=True)
            core.save_project(project);core.render(project['id'])
            result=core.read_project(project['id']);output=folder/result['exports'][-1]['file']
            video=next(s for s in core.probe(output)['streams'] if s['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(720,1280))
            ass=(output.parent/'subtitles.ass').read_text(encoding='utf-8')
            self.assertIn('PlayResX: 1080',ass)
            self.assertIn('PlayResY: 1920',ass)

    def test_default_asr_model_is_base(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'PRIVATE',Path(folder)):
            self.assertEqual(core.settings(True)['asr_model'],'base')

    def test_packaged_asr_model_is_reported_without_user_cache(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as cache:
            root=Path(folder);model=root/'engines'/'faster-whisper'/'base'
            model.mkdir(parents=True)
            for name in ('model.bin','config.json','tokenizer.json','vocabulary.txt'):
                (model/name).write_bytes(b'model')
            with patch.object(core,'ROOT',root), patch.dict('os.environ',{'HF_HUB_CACHE':cache}):
                self.assertEqual(core.cached_models(),['base'])

    def test_missing_asr_model_allows_first_download(self):
        with patch.dict(os.environ, {}, clear=True):
            env = core.transcription_environment(False)
            self.assertNotIn('HF_HUB_OFFLINE', env)

    def test_cached_asr_model_stays_offline(self):
        with patch.dict(os.environ, {}, clear=True):
            env = core.transcription_environment(True)
            self.assertEqual(env['HF_HUB_OFFLINE'], '1')

    def test_transcription_environment_reuses_complete_local_cuda_runtime(self):
        with tempfile.TemporaryDirectory() as folder:
            runtime=Path(folder)
            (runtime/'cublas64_12.dll').write_bytes(b'dll')
            (runtime/'cudnn_ops64_9.dll').write_bytes(b'dll')
            with patch.dict(os.environ,{'SCENEFLOW_CUDA_DLL_DIR':str(runtime),'PATH':''},clear=True):
                env=core.transcription_environment(True)
            self.assertEqual(Path(env['PATH'].split(os.pathsep)[0]),runtime.resolve())

    def test_explicit_offline_missing_model_has_actionable_error(self):
        detail = ('huggingface_hub.errors.LocalEntryNotFoundError: Cannot find an '
                  'appropriate cached snapshot folder; outgoing traffic has been disabled')
        message = core.transcription_error_message('base', detail)
        self.assertIn('联网后重试', message)
        self.assertNotIn('Traceback', message)

    def test_parse_silencedetect_pairs_ordered_intervals(self):
        text='silence_start: 11.160312\nsilence_end: 12.067146 | silence_duration: 0.906834\n'
        self.assertEqual(core.parse_silencedetect(text),[{'start':11.160312,'end':12.067146}])

    def test_aroll_framing_filter_is_static(self):
        medium=core.framing_filter(1920,1080,30,'medium')
        close=core.framing_filter(1920,1080,30,'medium_close')
        self.assertNotIn('zoompan=',medium);self.assertNotIn('zoompan=',close)
        self.assertIn('scale=2342:1318',close)

    def test_aroll_static_framing_filter_renders(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.mp4';output=Path(folder)/'motion.mp4'
            core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','color=c=navy:s=320x180:r=30:d=1',
                      '-c:v','libx264','-pix_fmt','yuv420p',source])
            core.run([core.FFMPEG,'-y','-v','error','-i',source,'-vf',core.framing_filter(320,180,30,'medium_close'),
                      '-frames:v','30','-c:v','libx264','-pix_fmt','yuv420p',output])
            info=core.probe(output);video=next(s for s in info['streams'] if s['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(320,180))

    def test_legacy_aroll_motion_is_migrated_to_hard_cut(self):
        project={'shots':[
            {'kind':'A','camera':'medium','visual_change':'push_in','motion':'push_in'},
            {'kind':'A','camera':'medium_close','visual_change':'pull_out','motion':'pull_out'},
            {'kind':'B','motion':'push_in'}]}
        self.assertTrue(core.normalize_aroll_hard_cuts(project))
        self.assertEqual(project['shots'][0],{'kind':'A','camera':'medium_close','visual_change':'cut_in','motion':None})
        self.assertEqual(project['shots'][1],{'kind':'A','camera':'medium','visual_change':'cut_out','motion':None})
        self.assertEqual(project['shots'][2]['motion'],'push_in')
        self.assertFalse(core.normalize_aroll_hard_cuts(project))

    def test_aroll_limit_counts_silence_tail_and_adjacent_runs(self):
        units=[{'id':0,'start':0,'end':4},{'id':1,'start':5,'end':9}]
        a={'from':0,'to':1,'kind':'A','title':'人物','reason':'','keywords':[]}
        core.validate_aroll_duration([a],units,10,10)
        with self.assertRaises(ValueError):core.validate_aroll_duration([a],units,10.001,10)
        split=[dict(a,to=0),dict(a,**{'from':1})]
        with self.assertRaises(ValueError):core.validate_aroll_duration(split,units,16.9,10)

    def test_deterministic_aroll_repair_matches_c1_boundary(self):
        units=[
            {'id':0,'start':0.0,'end':7.36,'text':'你上一次完全不看手机、不听音乐、不找任何事情做，'},
            {'id':1,'start':7.52,'end':10.56,'text':'纯粹发呆超过十分钟，'},
            {'id':2,'start':10.72,'end':13.12,'text':'是什么时候？'},
        ]
        group={'from':0,'to':2,'kind':'A','title':'开场提问','reason':'保留主持人','keywords':[]}
        result=core.deterministic_aroll_repair(group,units,13.28,10)
        self.assertEqual([(g['from'],g['to'],g['kind']) for g in result],[(0,0,'A'),(1,1,'B'),(2,2,'A')])
        self.assertEqual(result[1]['keywords'],['person sitting alone thinking'])
        core.validate_aroll_duration(result,units,13.28,10)

    def test_deterministic_aroll_repair_handles_one_indivisible_long_unit(self):
        units=[{'id':0,'start':0.0,'end':12.0,'text':'一条无法继续细分的长句'}]
        group={'from':0,'to':0,'kind':'A','title':'人物','reason':'','keywords':[]}
        result=core.deterministic_aroll_repair(group,units,12.0,10)
        self.assertEqual(result[0]['kind'],'B')
        self.assertTrue(result[0]['keywords'])

        # Episode-leading silence belongs to the opening shot and counts toward
        # the same hard limit.
        units=[{'id':0,'start':0.4,'end':9.9,'text':'开场长句'},
               {'id':1,'start':10.1,'end':10.3,'text':'短句'}]
        group={'from':0,'to':1,'kind':'A','title':'人物','reason':'','keywords':[]}
        result=core.deterministic_aroll_repair(group,units,10.3,10)
        self.assertEqual([g['kind'] for g in result],['B','A'])
        core.validate_aroll_duration(result,units,10.3,10)

        units=[{'id':0,'start':0,'end':1.9,'text':'结尾一'},
               {'id':1,'start':2.08,'end':6.3,'text':'结尾二'},
               {'id':2,'start':6.48,'end':9.5,'text':'中间承接'},
               {'id':3,'start':9.68,'end':13.84,'text':'最终结论'}]
        group={'from':0,'to':3,'kind':'A','title':'结尾','reason':'','keywords':[]}
        result=core.deterministic_aroll_repair(group,units,13.84,10)
        self.assertEqual((result[0]['kind'],result[-1]['kind']),('A','A'))
        core.validate_aroll_duration(result,units,13.84,10)

    def test_aroll_runs_merge_without_changing_broll_or_source(self):
        groups=[{'from':i,'to':i,'kind':kind,'title':str(i),'reason':'语义理由',
                 'keywords':['library'] if kind=='B' else []}
                for i,kind in enumerate('AAABBAA')]
        original=copy.deepcopy(groups)
        merged=core.merge_adjacent_aroll(groups)
        self.assertEqual([(g['from'],g['to'],g['kind']) for g in merged],
                         [(0,2,'A'),(3,3,'B'),(4,4,'B'),(5,6,'A')])
        self.assertEqual(merged[1:3],groups[3:5])
        self.assertEqual(groups,original)
        self.assertEqual(core.merge_adjacent_aroll(merged),merged)

    def test_plan_classifies_across_batches_then_builds_timeline(self):
        units=[{'id':i,'start':i*2+.2,'end':i*2+1.8,'text':f'原文{i}。'} for i in range(48)]
        p={'id':'test','segments':units,'duration':96.2,'shots':[],
           'options':{'broll_ratio':60,'max_shot':14},'revision':3}
        def segment(segment_id, ids, role, semantic_type, subject=''):
            return {'segment_id':segment_id,'candidate_ids':ids,
                    'text':''.join(units[i]['text'] for i in ids),
                    'semantic_type':semantic_type,'visual_role':role,'confidence':.94,
                    'entities':[],'visual_subject':subject,'evidence_required':False,
                    'evidence_target':None,'search_query':None,
                    'stock_search_query':'library reading' if role=='B' else None,
                    'stock_search_query_alt':['quiet library'] if role=='B' else [],
                    'fallback':'A','recording_required':False,'recording_instruction':None,
                    'motion_type':'M_NUMBER' if role=='M' else None,
                    'generation_concept':None,'importance':3,
                    'continuity_group':'CG01','reason':'整片视觉导演验收'}
        response={'video_type':'general','overview':'测试','segments':[
            segment('S001',[0],'A','hook'),
            segment('S002',list(range(1,47)),'B','event','图书馆阅读'),
            segment('S003',[47],'A','summary'),
        ]}
        with patch.object(core,'read_project',side_effect=lambda _:copy.deepcopy(p)), \
             patch.object(core,'settings',return_value={'llm_provider':'deepseek','llm_api_key':'key'}), \
             patch.object(core,'progress'), patch.object(core,'save_project') as save, \
             patch.object(core,'chat_json',return_value=response) as chat:
            core.plan('test')
        result=save.call_args.args[0];shots=result['shots']
        self.assertEqual((shots[0]['kind'],shots[-1]['kind']),('A','A'))
        self.assertEqual({s['visual_role'] for s in shots},{'A','B'})
        self.assertTrue(all(round(s['end']-s['start'],3)<=5.01 for s in shots if s['kind']=='B'))
        self.assertEqual(result['segments'],units)
        self.assertEqual(len(result['candidate_segments']),48)
        self.assertEqual(result['analysis']['llm_role'],'visual_director_semantics_only')
        self.assertEqual(result['visual_master_plan']['segments'][0]['visual_role'],'A')
        self.assertEqual(result['visual_master_plan']['segments'][1]['visual_role'],'B')
        core.validate_timeline(shots,p['duration'])
        request=json.loads(chat.call_args.args[1][1]['content'])
        self.assertNotIn('start',json.dumps(request,ensure_ascii=False))
        self.assertNotIn('duration',json.dumps(request,ensure_ascii=False))
        self.assertEqual(request['candidates'][0]['id'],0)
        self.assertEqual(p['shots'],[])

    def test_visual_director_schema_failure_uses_legacy_storyboard_fallback(self):
        units=[
            {'id':0,'start':0,'end':2.8,'text':'主持人开场。'},
            {'id':1,'start':3.0,'end':5.8,'text':'办公室里的工作场景。'},
            {'id':2,'start':6.0,'end':8.8,'text':'主持人总结。'},
        ]
        p={'id':'fallback','segments':units,'duration':8.8,'shots':[],
           'options':{'broll_ratio':60,'max_shot':14},'revision':0,'video_profile':'general'}
        invalid={'video_type':'general','overview':'bad','segments':[
            {'segment_id':'S001','candidate_ids':[0],'text':units[0]['text'],
             'semantic_type':'hook','visual_role':'A'},
        ]}
        legacy={'segments':[
            {'id':0,'text':units[0]['text'],'semantic_type':'hook','visual_subject':'','importance':'normal','emotion':'neutral'},
            {'id':1,'text':units[1]['text'],'semantic_type':'event','visual_subject':'办公室工作','importance':'normal','emotion':'neutral'},
            {'id':2,'text':units[2]['text'],'semantic_type':'summary','visual_subject':'','importance':'normal','emotion':'neutral'},
        ]}
        with patch.object(core,'read_project',side_effect=lambda _:copy.deepcopy(p)), \
             patch.object(core,'settings',return_value={'llm_provider':'deepseek','llm_api_key':'key'}), \
             patch.object(core,'progress'),patch.object(core,'save_project') as save, \
             patch.object(core,'chat_json',side_effect=[invalid,invalid,legacy]) as chat:
            core.plan('fallback')
        result=save.call_args.args[0]
        self.assertEqual(result['analysis']['visual_director_status'],'fallback')
        self.assertEqual(result['shots'][0]['kind'],'A')
        self.assertEqual(result['shots'][-1]['kind'],'A')
        self.assertEqual(chat.call_count,3)

    def test_broll_split_preserves_a_and_selected_first_take(self):
        for duration in (4,4.001,4.84,5.92,7.84,9.14,16):
            a={'id':'a','kind':'A','start':0,'end':6,'aroll_asset':'existing.mp4'}
            b={'id':'b','kind':'B','start':6,'end':6+duration,'asset':'chosen.mp4',
               'source':{'id':'selected'},'media_start':2,'title':'手机','text':'关联原文','from':1,'to':3,
               'keywords':['phone'],'candidates':[{'id':'selected'}]}
            before=copy.deepcopy([a,b]);units=[{'start':8.2},{'start':9.5}]
            result=core.split_long_broll([a,b],units)
            self.assertEqual(result[0],a)
            self.assertEqual([a,b],before)
            self.assertEqual(result[1]['asset'],'chosen.mp4')
            self.assertEqual(result[1]['media_start'],2)
            self.assertTrue(all(round(s['end']-s['start'],3)<=4 for s in result[1:]))
            if duration>4:
                self.assertTrue(all(round(s['end']-s['start'],3)>=2 for s in result[1:]))
                self.assertTrue(all(s['asset'] is None and s['source'] is None for s in result[2:]))
            self.assertEqual(len({s['id'] for s in result}),len(result))
            self.assertEqual(core.split_long_broll(result,units),result)
            core.validate_timeline(result,6+duration)

    def test_materials_never_reuses_adjacent_broll_automatically(self):
        import tempfile
        for allow_alternative in (False,True):
            with tempfile.TemporaryDirectory() as directory:
                folder=Path(directory);(folder/'chosen.mp4').touch()
                p={'id':'test','options':{'source':'pexels'},'revision':0,'shots':[
                    {'id':'first','kind':'B','start':0,'end':4,'title':'原素材',
                     'asset':'chosen.mp4','source':{'id':'same'}},
                    {'id':'next','kind':'B','start':4,'end':8,'title':'新画面','keywords':['phone'],
                     'asset':None,'source':None}]}
                found=[{'id':'same','duration':10,'width':1920,'height':1080}]
                if allow_alternative:found.append(dict(found[0],id='different'))
                def save(updated):p.update(copy.deepcopy(updated))
                with patch.object(core,'read_project',side_effect=lambda _:copy.deepcopy(p)), \
                     patch.object(core,'settings',return_value={}),patch.object(core,'progress'), \
                     patch.object(core,'project_dir',return_value=folder), \
                     patch.object(core,'search_stock',return_value=found), \
                     patch.object(core,'stash_candidates',side_effect=lambda pid,sid,cs:cs), \
                     patch.object(core,'save_project',side_effect=save), \
                     patch.object(core,'download_candidate',return_value='different.mp4') as download:
                    core.materials('test')
                self.assertEqual(p['shots'][0]['source']['id'],'same')
                if allow_alternative:
                    self.assertEqual(p['shots'][1]['source']['id'],'different')
                    self.assertEqual(download.call_count,1)
                else:
                    download.assert_not_called()
                    self.assertEqual(p['shots'][1]['material_status'],'missing')

    def test_stock_search_requests_a_larger_candidate_pool(self):
        response=Mock(status_code=200);response.json.return_value={'videos':[]}
        with patch.object(core.requests,'get',return_value=response) as get:
            self.assertEqual(core.search_stock('library','pexels',{'pexels_api_key':'key'}),[])
        self.assertEqual(core.CANDIDATE_LIMIT,12)
        self.assertEqual(get.call_args.kwargs['params']['per_page'],12)
        self.assertEqual(get.call_args.kwargs['params']['orientation'],'landscape')

    def test_stock_search_follows_landscape_square_and_portrait_shapes(self):
        pexels=Mock(status_code=200);pexels.json.return_value={'videos':[{
            'id':1,'duration':8,'url':'https://pexels.example/video','user':{'name':'author'},'image':'https://example/thumb.jpg',
            'video_files':[
                {'file_type':'video/mp4','width':1920,'height':1080,'link':'https://example/land.mp4'},
                {'file_type':'video/mp4','width':1080,'height':1080,'link':'https://example/square.mp4'},
                {'file_type':'video/mp4','width':1080,'height':1920,'link':'https://example/portrait.mp4'},
            ]}]}
        for aspect,expected,orientation in (('16:9',(1920,1080),'landscape'),('1:1',(1080,1080),'square'),('9:16',(1080,1920),'portrait')):
            with patch.object(core.requests,'get',return_value=pexels) as get:
                result=core.search_stock('library','pexels',{'pexels_api_key':'key'},
                                         {'aspect_ratio':aspect,'resolution':'1080p'})
            self.assertEqual((result[0]['width'],result[0]['height']),expected)
            self.assertEqual(result[0]['target_aspect_ratio'],aspect)
            self.assertEqual(get.call_args.kwargs['params']['orientation'],orientation)

        pixabay=Mock(status_code=200);pixabay.json.return_value={'hits':[
            {'id':1,'duration':8,'pageURL':'https://example/1','user':'a','videos':{'large':{'width':1920,'height':1080,'url':'https://example/1.mp4'}}},
            {'id':2,'duration':8,'pageURL':'https://example/2','user':'b','videos':{'large':{'width':1080,'height':1080,'url':'https://example/2.mp4'}}},
            {'id':3,'duration':8,'pageURL':'https://example/3','user':'c','videos':{'large':{'width':1080,'height':1920,'url':'https://example/3.mp4'}}},
        ]}
        for aspect,expected_id in (('16:9','pixabay-1'),('1:1','pixabay-2'),('9:16','pixabay-3')):
            with patch.object(core.requests,'get',return_value=pixabay):
                result=core.search_stock('library','pixabay',{'pixabay_api_key':'key'},
                                         {'aspect_ratio':aspect,'resolution':'1080p'})
            self.assertEqual([item['id'] for item in result],[expected_id])

    def test_switching_aspect_preserves_each_stock_selection(self):
        project={'shots':[{'id':'b1','kind':'B','asset':'assets/land.mp4','source':{'provider':'pexels','id':'land'},
                           'media_start':1,'material_status':'ready','material_error':None,'candidates':[{'id':'land'}]}]}
        self.assertTrue(core.switch_broll_aspect(project,'16:9','9:16'))
        shot=project['shots'][0]
        self.assertIsNone(shot['asset'])
        self.assertEqual(shot['material_status'],'pending')
        shot.update(asset='assets/portrait.mp4',source={'provider':'pexels','id':'portrait'},media_start=0,
                    material_status='ready',material_error=None,candidates=[{'id':'portrait'}])
        self.assertTrue(core.switch_broll_aspect(project,'9:16','16:9'))
        self.assertEqual(shot['asset'],'assets/land.mp4')
        self.assertEqual(shot['source']['id'],'land')
        self.assertTrue(core.switch_broll_aspect(project,'16:9','9:16'))
        self.assertEqual(shot['asset'],'assets/portrait.mp4')
        self.assertEqual(shot['source']['id'],'portrait')

    def test_materials_randomizes_fresh_episode_wide_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            p={'id':'test','options':{'source':'pexels'},'revision':0,'shots':[
                {'id':'old','kind':'B','start':0,'end':4,'title':'旧素材','asset':'old.mp4','source':{'id':'used'}},
                {'id':'host','kind':'A','start':4,'end':8,'title':'人物','asset':None,'source':None},
                {'id':'next','kind':'B','start':8,'end':12,'title':'新画面','keywords':['library'],'asset':None,'source':None}]}
            (folder/'old.mp4').touch()
            found=[{'id':name,'duration':10,'width':1920,'height':1080}
                   for name in ('used','first','middle','last')]
            def save(updated):p.update(copy.deepcopy(updated))
            def reverse(items):items.reverse()
            with patch.object(core,'read_project',side_effect=lambda _:copy.deepcopy(p)), \
                 patch.object(core,'settings',return_value={}),patch.object(core,'progress'), \
                 patch.object(core,'project_dir',return_value=folder), \
                 patch.object(core,'search_stock',return_value=found), \
                 patch.object(core,'stash_candidates',side_effect=lambda pid,sid,cs:cs), \
                 patch.object(core.random,'shuffle',side_effect=reverse), \
                 patch.object(core,'save_project',side_effect=save), \
                 patch.object(core,'download_candidate',side_effect=lambda pid,c:f'{c["id"]}.mp4') as download:
                core.materials('test')
            self.assertEqual(p['shots'][2]['source']['id'],'last')
            self.assertNotEqual(p['shots'][2]['source']['id'],'used')
            self.assertEqual(download.call_count,1)

    def test_complete_partition_only(self):
        units=[{'id':i} for i in range(5,9)]
        good=[{'from':5,'to':6,'kind':'A','keywords':[]},{'from':7,'to':8,'kind':'B','keywords':['library']}]
        self.assertEqual(len(core.validate_plan(good,units)),2)
        for bad in ([good[0]], [{'from':6,'to':8,'kind':'A'}], [good[0],{'from':6,'to':8,'kind':'B'}], [{'from':5,'to':8,'kind':'C'}], [{'from':5,'to':8,'kind':'B','keywords':[]}]):
            with self.assertRaises(ValueError): core.validate_plan(bad,units)

    def test_wrapper_shot_salvage_and_string_ids(self):
        # 某些结构化回复会在真实分镜之上输出一个覆盖整批的概括镜头；应裁剪为开头未覆盖段而非整体失败。
        units=[{'id':i} for i in range(16)]
        wrapper=[{'from':0,'to':15,'kind':'A','keywords':[]},
                 {'from':3,'to':4,'kind':'B','keywords':['lab']},
                 {'from':5,'to':6,'kind':'B','keywords':['brain']},
                 {'from':7,'to':8,'kind':'B','keywords':['anxiety']},
                 {'from':9,'to':10,'kind':'B','keywords':['brain']},
                 {'from':11,'to':12,'kind':'B','keywords':['memory']},
                 {'from':13,'to':14,'kind':'B','keywords':['time']},
                 {'from':15,'to':15,'kind':'A','keywords':[]}]
        plan=core.validate_plan(wrapper,units)
        self.assertEqual([(g['from'],g['to'],g['kind']) for g in plan],
                         [(0,2,'A'),(3,4,'B'),(5,6,'B'),(7,8,'B'),(9,10,'B'),(11,12,'B'),(13,14,'B'),(15,15,'A')])
        # 概括镜头之后其余镜头从 0 重新完整编号：概括镜头应被整体丢弃
        renumbered=[{'from':0,'to':15,'kind':'A','keywords':[]},
                    {'from':0,'to':1,'kind':'B','keywords':['stare']},
                    {'from':2,'to':2,'kind':'B','keywords':['clock']}]
        renumbered+=[{'from':i,'to':i,'kind':'B','keywords':['room']} for i in range(3,16)]
        plan2=core.validate_plan(renumbered,units)
        self.assertEqual([(g['from'],g['to']) for g in plan2],
                         [(0,1),(2,2),(3,3),(4,4),(5,5),(6,6),(7,7),(8,8),(9,9),(10,10),(11,11),(12,12),(13,13),(14,14),(15,15)])
        stringed=[{'from':'0','to':'15','kind':'B','keywords':['library']}]
        self.assertEqual(core.validate_plan(stringed,units)[0]['from'],0)
        # 中间出现真实缺口仍必须拒绝
        gapped=[{'from':5,'to':6,'kind':'A','keywords':[]},{'from':8,'to':8,'kind':'A','keywords':[]}]
        # 模型把全部镜头都标成 B（开场/结尾也没有人物）：开场与结尾应被锚定回 A
        all_b=[{'from':i,'to':i,'kind':'B','keywords':['man sitting']} for i in range(16)]
        plan3=core._ensure_anchor_aroll(core.validate_plan(core.merge_adjacent_aroll(all_b),units))
        self.assertEqual(plan3[0]['kind'],'A'); self.assertEqual(plan3[-1]['kind'],'A')
        self.assertEqual(sum(g['kind']=='A' for g in plan3),2)
        self.assertTrue(all(not g['keywords'] for g in plan3 if g['kind']=='A'))
        # 即使中间已有 A，结尾仍应回到人物。
        with_a=[{'from':0,'to':2,'kind':'A','keywords':[]},{'from':3,'to':15,'kind':'B','keywords':['library']}]
        anchored=core._ensure_anchor_aroll(with_a)
        self.assertEqual((anchored[0]['kind'],anchored[-1]['kind']),('A','A'))
        with self.assertRaises(ValueError): core.validate_plan(gapped,units)

    def test_srt_audio_bounds_and_overlap(self):
        text='1\n00:00:00,250 --> 00:00:02,000\n第一句话\n\n2\n00:00:02,100 --> 00:00:04,000\n第二句话\n'
        self.assertEqual(len(core.parse_srt(text,4)),2)
        with self.assertRaises(ValueError):core.parse_srt(text,2)
        with self.assertRaises(ValueError):core.parse_srt(text.replace('00:00:02,100','00:00:01,500'),4)
        with self.assertRaises(ValueError):core.normalize_segments([{'start':float('nan'),'end':3,'text':'test'}],4)

    def test_timeline_keeps_audio_length(self):
        shots=[{'start':0,'end':1.341,'kind':'A'},{'start':1.341,'end':3.121,'kind':'B'}]
        core.validate_timeline(shots,3.121)
        self.assertEqual(sum(round(s['end']*30)-round(s['start']*30) for s in shots),round(3.121*30))
        for start in (1.5,1.1,float('nan')):
            bad=copy.deepcopy(shots);bad[1]['start']=start
            with self.assertRaises(ValueError):core.validate_timeline(bad,3.121)

    def test_caption_timing_does_not_mutate_transcript(self):
        p={'segments':[{'start':1,'end':12,'text':'这是很长的中文测试字幕。'*8}]};before=copy.deepcopy(p)
        events=core.subtitle_events(p)
        self.assertEqual(p,before); self.assertAlmostEqual(events[-1]['end'],12)
        self.assertEqual(''.join(e['text'] for e in events),p['segments'][0]['text'])
        self.assertTrue(all(e['end']>e['start'] for e in events))

    def test_caption_lines_never_cut_a_latin_word_in_half(self):
        text=('另一段来自 OpenAI 负责推理研究的 Noam Brown，他说 Hugging Face 事件真正说明的是'
              '人们低估了 AI，而 Gemini 由第三方机构 Irregular 执行。')
        parts=core._caption_parts(text)
        self.assertEqual(''.join(parts).replace(' ',''),text.replace(' ',''))
        for token in ('OpenAI','Noam Brown','Hugging Face','Gemini','Irregular'):
            self.assertTrue(any(token in part for part in parts),f'{token} 被拆断了：{parts}')
        self.assertFalse(any(part.strip() in ('is，','lar 执行。') for part in parts))

    def test_caption_lines_break_at_clauses_and_keep_the_punctuation(self):
        parts=core._caption_parts('据 The Verge 援引《华尔街日报》的报道，今年 5 月，Gemini 越了界。')
        self.assertTrue(parts[0].endswith('，'),parts)
        self.assertTrue(parts[-1].endswith('。'),parts)
        for part in parts:
            # A clause whose tail would be too short to read stays whole, so a
            # line may run a couple of characters past the display limit.
            self.assertLessEqual(len(part),26,part)
            self.assertGreaterEqual(len(part.strip()),4,part)

    def test_punctuation_only_caption_fragments_join_the_line_they_close(self):
        self.assertEqual(core._caption_parts('而是“身份误认”，'), ['而是“身份误认”，'])
        quoted=core._caption_parts('特朗普政府则直接把 AI 安全危机称为“骗局”。')
        self.assertEqual(len(quoted),1,quoted)
        self.assertTrue(quoted[0].endswith('。'))

    def test_project_relative_survives_a_differently_spelled_root(self):
        # Windows returns 8.3 short names for temporary directories, so the same
        # folder can be spelled two ways and a plain relative_to() raises.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            target=root/'assets'/'clip.mp4'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'x')
            self.assertEqual(core.project_relative(target,root),'assets/clip.mp4')
            odd=root/'assets'/'..'
            self.assertEqual(core.project_relative(target,odd),'assets/clip.mp4')

    def test_credentials_are_not_public(self):
        public=core.settings(); private=core.settings(True)
        for key,value in private.items():
            if key.endswith('api_key'):
                self.assertNotIn(key,public)
                if value:self.assertNotIn(value,json.dumps(public))
        self.assertEqual(core.public_page('https://example.com/file?token=secret#x'),'https://example.com/file')
        self.assertEqual(core.public_page('https://user:password@example.com/x'),'')

if __name__=='__main__':unittest.main()
