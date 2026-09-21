import base64, copy, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient
import core, server, local_engines as le, tts_common as tc, model_client, voice_tts

class LocalEngineTests(unittest.TestCase):
    def test_phrases_preserve_script_and_cache_changes_with_voice(self):
        for text in ['你好，今天我们读一本书。\n再谈谈生活！', 'A sentence. Another sentence, with a pause.', '很长的原稿'*55]:
            parts=tc.split_script(text)
            self.assertEqual(''.join(parts),text)
            self.assertTrue(all(len(x)<=80 for x in parts))
        self.assertEqual(tc.split_script('你好，今天我们测试新的联网配音。'),['你好，今天我们测试新的联网配音。'])
        self.assertNotEqual(tc.signature('原稿','zh-CN-XiaoxiaoNeural','Chinese'),tc.signature('原稿','zh-CN-YunxiNeural','Chinese'))
        self.assertNotEqual(tc.signature('原稿','zh-CN-XiaoxiaoNeural','Chinese','azure-v1',1),tc.signature('原稿','zh-CN-XiaoxiaoNeural','Chinese','azure-v1',1.1))
        self.assertNotEqual(tc.signature('原稿','index-reference','Chinese','indextts25',1,'assets/a.wav'),tc.signature('原稿','index-reference','Chinese','indextts25',1,'assets/b.wav'))

    def test_three_tts_providers_are_validated(self):
        default=le.validate_script({'text':'默认配音'})
        self.assertEqual(default['provider'],'azure-v1')
        self.assertEqual(default['speaker'],'zh-CN-XiaoxiaoNeural')
        self.assertEqual(default['speed'],1.0)
        self.assertEqual(le.validate_script({'text':'新原稿','speaker':'unknown','language':'Chinese'})['speaker'],'zh-CN-XiaoxiaoNeural')
        self.assertEqual(le.validate_script({'text':'English text','provider':'azure-v1','speaker':'unknown','language':'English'})['speaker'],'en-US-AvaNeural')
        seed=le.validate_script({'text':'豆包','provider':'seed-audio','speaker':'seed-natural-female','language':'Chinese'})
        self.assertEqual(seed['speaker'],'seed-natural-female')
        index=le.validate_script({'text':'本地','provider':'indextts25','reference':'assets/voice.wav','language':'Chinese'},require_reference=True)
        self.assertEqual(index['speaker'],'index-reference')
        with self.assertRaisesRegex(ValueError,'参考声音'):
            le.validate_script({'text':'本地','provider':'indextts25','language':'Chinese'},require_reference=True)
        with self.assertRaisesRegex(ValueError,'支持的配音引擎'):
            le.validate_script({'text':'本地','provider':'local','language':'Chinese'})

    def test_indextts25_graph_matches_proven_workbench_nodes(self):
        graph=voice_tts.build_index_prompt('你好','voice.wav','speaker',1.0,42,'SceneFlow/test')
        self.assertEqual(graph['1']['class_type'],'JR_IndexTTS25_Loader')
        self.assertEqual(graph['3']['class_type'],'JR_IndexTTS25_VoicePreset')
        self.assertEqual(graph['4']['class_type'],'JR_IndexTTS25_Generate')
        self.assertEqual(graph['4']['inputs']['language'],'ZH')
        self.assertEqual(graph['4']['inputs']['duration_factor'],1.0)
        self.assertEqual(graph['7']['class_type'],'SaveAudio')

    def test_seed_connection_check_never_spends_a_generation(self):
        with patch.object(voice_tts.requests,'post') as post:
            result=voice_tts.test_seed_connection({'tts_seed_api_key':'configured-secret'})
        self.assertTrue(result['ok'])
        post.assert_not_called()

    def test_seed_audio_request_uses_existing_api_contract_without_leaking_key(self):
        response=Mock(status_code=200,reason='OK')
        response.json.return_value={'code':0,'audio':base64.b64encode(b'RIFF'+b'\0'*80).decode()}
        script={'speaker':'seed-natural-female'}
        with tempfile.TemporaryDirectory() as root,patch.object(voice_tts.requests,'post',return_value=response) as post:
            folder=Path(root);raw=folder/'voice.audio';request_file=folder/'request.json'
            voice_tts._seed_chunk({'tts_seed_api_key':'private-key'},script,None,'你好',raw,request_file)
            self.assertGreater(raw.stat().st_size,44)
            saved=request_file.read_text(encoding='utf-8')
            self.assertNotIn('private-key',saved)
            body=post.call_args.kwargs['json']
            self.assertEqual(body['model'],'seed-audio-1.0')
            self.assertEqual(body['audio_config']['sample_rate'],24000)
            self.assertEqual(post.call_args.kwargs['headers']['X-Api-Key'],'private-key')

    def test_draft_does_not_destroy_existing_work_and_blocks_stale_export(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'PROJECTS',Path(root)),TestClient(server.app) as client:
            p=core.create_project('existing');pid=p['id']
            p.update(audio='assets/old.wav',segments=[{'text':'旧声音'}],shots=[{'id':'old'}],exports=[{'file':'old.mp4'}]);core.save_project(p)
            r=client.put(f'/api/projects/{pid}/script',json={'text':'新原稿','speaker':'zf_xiaoni','language':'Chinese'})
            self.assertEqual(r.status_code,200,r.text)
            for key in ('audio','segments','exports'):self.assertEqual(r.json()[key],p[key])
            self.assertEqual(r.json()['shots'][0]['id'],'old')
            self.assertEqual(r.json()['shots'][0]['visual_role'],'A')
            self.assertEqual(client.post(f'/api/projects/{pid}/jobs',json={'action':'render'}).status_code,400)
            core.ACTIVE[pid]={'cancel':False}
            try:self.assertEqual(client.put(f'/api/projects/{pid}/script',json={'text':'other'}).status_code,400)
            finally:core.ACTIVE.pop(pid,None)

    def test_new_text_job_and_resume_skip_successful_tts_and_asr(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'PROJECTS',Path(root)):
            p=core.create_project('text');pid=p['id'];p['script']={'text':'你好','provider':'azure-v1','speaker':'zh-CN-XiaoxiaoNeural','language':'Chinese','speed':1};core.save_project(p)
            # `all` now performs the user-facing provider preflight.  This
            # test exercises resume/caching behavior after that gate, so keep
            # the preflight itself out of the fixture.
            with patch('core.threading.Thread'), patch.object(
                core, 'generation_preflight', return_value={'ok': True, 'issues': []}
            ):
                core.start_job(pid,'all')
            def synthesize(_):
                q=core.read_project(pid);q.update(audio='done.wav',segments=[{'text':'你好'}],tts={'signature':tc.signature(**q['script'])});core.save_project(q)
            def plan(_):
                q=core.read_project(pid);q['shots']=[{'kind':'A'}];core.save_project(q)
            with patch.object(le,'synthesize',side_effect=synthesize) as tts,patch.object(core,'transcribe') as asr,patch.object(core,'plan',side_effect=plan) as planner,patch.object(core,'materials'),patch('aroll.generate'),patch.object(core,'render'):
                core.job_worker(pid,'all');core.ACTIVE[pid]={'cancel':False};core.job_worker(pid,'all')
                self.assertEqual(tts.call_count,1);self.assertEqual(planner.call_count,1);self.assertEqual(asr.call_count,1)

    def test_bad_voice_and_empty_text_rejected(self):
        for value in ({'text':''},{'text':'x'*20001},{'text':'hi','provider':'evil'},{'text':'hi','speed':3}):
            with self.assertRaises(ValueError):le.validate_script(value)

    def test_deepseek_json_disables_thinking_and_preserves_config(self):
        cfg={'provider':'deepseek','name':'DeepSeek','base_url':'https://api.deepseek.com','model':'deepseek-v4-flash','api_key':'token','type':'openai-compatible','request_options':{'thinking':{'type':'disabled'}}}
        before=copy.deepcopy(cfg);response=Mock(status_code=200,headers={},content=b'{}')
        response.json.return_value={'choices':[{'finish_reason':'stop','message':{'content':'{"shots":[]}'}}]}
        with patch('model_client.requests.post',return_value=response) as post:
            model_client.request_json(cfg,[{'role':'user','content':'JSON'}])
            self.assertEqual(post.call_args.kwargs['json']['thinking'],{'type':'disabled'})
            self.assertEqual(cfg,before)

    def test_editorial_guard_rejects_all_b_and_repetition(self):
        units=[{'id':i,'start':i*3,'end':i*3+2,'text':'原文'} for i in range(6)]
        all_b=[{'from':i,'to':i,'kind':'B','title':'发呆','reason':'','keywords':['man sitting']} for i in range(6)]
        with self.assertRaisesRegex(ValueError,'开场和结尾'):
            core.validate_local_editorial_quality(all_b,units,18,60)
        repeated=[dict(all_b[0],kind='A',keywords=[]),*all_b[1:5],dict(all_b[5],kind='A',keywords=[])]
        with self.assertRaisesRegex(ValueError,'反复使用'):
            core.validate_local_editorial_quality(repeated,units,18,60)

if __name__=='__main__':unittest.main()
