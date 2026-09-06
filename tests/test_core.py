import copy, json, math, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core
from unittest.mock import patch

class TimelineTests(unittest.TestCase):
    def test_parse_silencedetect_pairs_ordered_intervals(self):
        text='silence_start: 11.160312\nsilence_end: 12.067146 | silence_duration: 0.906834\n'
        self.assertEqual(core.parse_silencedetect(text),[{'start':11.160312,'end':12.067146}])

    def test_aroll_motion_filter_is_seek_safe_and_directional(self):
        push=core.framing_filter(1920,1080,30,150,'medium','push_in',.08)
        pull=core.framing_filter(1920,1080,30,150,'medium_close','pull_out',.08)
        self.assertIn("1+0.08*on/149",push)
        self.assertIn("1+0.08*(1-on/149)",pull)
        self.assertIn('zoompan=',push);self.assertIn('scale=2342:1318',pull)

    def test_aroll_motion_filter_renders(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source.mp4';output=Path(folder)/'motion.mp4'
            core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','color=c=navy:s=320x180:r=30:d=1',
                      '-c:v','libx264','-pix_fmt','yuv420p',source])
            core.run([core.FFMPEG,'-y','-v','error','-i',source,'-vf',core.framing_filter(320,180,30,30,'medium','push_in',.08),
                      '-frames:v','30','-c:v','libx264','-pix_fmt','yuv420p',output])
            info=core.probe(output);video=next(s for s in info['streams'] if s['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(320,180))

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

    def test_long_broll_run_returns_to_host(self):
        units=[{'id':i,'start':i*4,'end':i*4+3.8,'text':f'原文{i}'} for i in range(10)]
        groups=[
            {'from':0,'to':0,'kind':'A','title':'开场','reason':'','keywords':[]},
            {'from':1,'to':8,'kind':'B','title':'示意','reason':'语义素材','keywords':['person thinking']},
            {'from':9,'to':9,'kind':'A','title':'结尾','reason':'','keywords':[]},
        ]
        result=core.rebalance_long_broll_runs(groups,units,40,12,5,10)
        self.assertGreater(sum(g['kind']=='A' for g in result),2)
        self.assertLessEqual(core.max_kind_run_duration(result,units,40,'B'),12)
        self.assertLessEqual(core.max_kind_run_duration(result,units,40,'A'),10)
        self.assertTrue(any(g['title']=='人物回场' for g in result))
        self.assertTrue(all(g['keywords']==['person thinking'] for g in result if g['kind']=='B'))

        # A long B run between two nearly-full A runs needs a boundary swap;
        # simply changing a B phrase to A would make the neighboring A exceed 10s.
        units=[{'id':i,'start':i*4,'end':i*4+3.8,'text':f'原文{i}'} for i in range(8)]
        groups=[
            {'from':0,'to':1,'kind':'A','title':'人物','reason':'','keywords':[]},
            {'from':2,'to':5,'kind':'B','title':'示意','reason':'','keywords':['person thinking']},
            {'from':6,'to':7,'kind':'A','title':'人物','reason':'','keywords':[]},
        ]
        result=core.rebalance_long_broll_runs(groups,units,32,12,5,10)
        self.assertLessEqual(core.max_kind_run_duration(result,units,32,'B'),12)
        self.assertLessEqual(core.max_kind_run_duration(result,units,32,'A'),10)
        self.assertEqual((result[0]['kind'],result[-1]['kind']),('A','A'))

    def test_plan_classifies_across_batches_then_builds_timeline(self):
        units=[{'id':i,'start':i*2+.2,'end':i*2+1.8,'text':f'原文{i}。'} for i in range(48)]
        p={'id':'test','segments':units,'duration':96.2,'shots':[],
           'options':{'broll_ratio':60,'max_shot':14},'revision':3}
        def semantic(unit):
            semantic_type='hook' if unit['id']==0 else 'summary' if unit['id']==47 else 'event'
            return {'id':unit['id'],'text':unit['text'],'semantic_type':semantic_type,
                    'visual_subject':'' if semantic_type in ('hook','summary') else '图书馆阅读',
                    'importance':'normal','emotion':'neutral'}
        responses=[{'segments':[semantic(unit) for unit in units[:45]]},
                   {'segments':[semantic(unit) for unit in units[45:]]}]
        with patch.object(core,'read_project',side_effect=lambda _:copy.deepcopy(p)), \
             patch.object(core,'settings',return_value={'llm_model':'test','llm_api_key':'key'}), \
             patch.object(core,'progress'), patch.object(core,'save_project') as save, \
             patch.object(core,'chat_json',side_effect=responses) as chat:
            core.plan('test')
        result=save.call_args.args[0];shots=result['shots']
        self.assertEqual((shots[0]['kind'],shots[-1]['kind']),('A','A'))
        self.assertTrue(all(round(s['end']-s['start'],3)<=6.01 for s in shots if s['kind']=='B'))
        self.assertEqual(result['segments'],units)
        self.assertEqual(len(result['candidate_segments']),48)
        self.assertEqual(result['analysis']['llm_role'],'semantic_classification_only')
        core.validate_timeline(shots,p['duration'])
        second_input=json.loads(chat.call_args_list[1].args[1][1]['content'])
        self.assertNotIn('start',json.dumps(second_input,ensure_ascii=False))
        self.assertNotIn('duration',json.dumps(second_input,ensure_ascii=False))
        self.assertEqual(second_input['candidates'][0]['id'],45)
        self.assertEqual(p['shots'],[])

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

    def test_credentials_are_not_public(self):
        public=core.settings(); private=core.settings(True)
        for key,value in private.items():
            if key.endswith('api_key'):
                self.assertNotIn(key,public)
                if value:self.assertNotIn(value,json.dumps(public))
        self.assertEqual(core.public_page('https://example.com/file?token=secret#x'),'https://example.com/file')
        self.assertEqual(core.public_page('https://user:password@example.com/x'),'')

if __name__=='__main__':unittest.main()
