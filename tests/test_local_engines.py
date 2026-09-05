import copy, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient
import core, server, local_engines as le, tts_worker as tw, model_client, engine_setup

class LocalEngineTests(unittest.TestCase):
    def test_phrases_preserve_script_and_cache_changes_with_voice(self):
        for text in ['你好，今天我们读一本书。\n再谈谈生活！', 'A sentence. Another sentence, with a pause.', '很长的原稿'*55]:
            parts=tw.split_script(text)
            self.assertEqual(''.join(parts),text)
            self.assertTrue(all(len(x)<=80 for x in parts))
        self.assertEqual(tw.split_script('你好，今天我们测试新的本地配音。'),['你好，今天我们测试新的本地配音。'])
        self.assertNotEqual(tw.signature('原稿','zf_xiaoni','Chinese'),tw.signature('原稿','zm_yunxi','Chinese'))
        self.assertNotEqual(tw.signature('原稿','zh-CN-XiaoxiaoNeural','Chinese','azure-v1',1),tw.signature('原稿','zh-CN-XiaoxiaoNeural','Chinese','azure-v1',1.1))
        self.assertEqual(set(tw.SPEAKERS),set(engine_setup.KOKORO_VOICES))
        self.assertNotIn('zf_xiaoyan',tw.SPEAKERS)

    def test_azure_is_default_and_legacy_projects_stay_renderable(self):
        default=le.validate_script({'text':'默认配音'})
        self.assertEqual(default['provider'],'azure-v1')
        self.assertEqual(default['speaker'],'zh-CN-XiaoxiaoNeural')
        self.assertEqual(default['speed'],1.0)
        old={'script':{'text':'旧原稿','speaker':'Uncle_Fu','language':'Chinese'},'audio':'old.wav',
             'tts':{'text':'旧原稿','speaker':'Uncle_Fu','language':'Chinese','engine':'Qwen3-TTS'}}
        self.assertFalse(le.needs_tts(old))
        old['script']={**old['script'],'text':'新原稿'}
        self.assertTrue(le.needs_tts(old))
        self.assertEqual(le.validate_script({'text':'新原稿','speaker':'Uncle_Fu','language':'Chinese'})['speaker'],'zh-CN-YunyangNeural')
        self.assertEqual(le.validate_script({'text':'English text','provider':'azure-v1','speaker':'zf_xiaoni','language':'English'})['speaker'],'en-US-AvaNeural')
        self.assertEqual(le.validate_script({'text':'本地','provider':'kokoro','speaker':'Uncle_Fu','language':'Chinese'})['speaker'],'zm_yunyang')

    def test_draft_does_not_destroy_existing_work_and_blocks_stale_export(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'PROJECTS',Path(root)),TestClient(server.app) as client:
            p=core.create_project('existing');pid=p['id']
            p.update(audio='assets/old.wav',segments=[{'text':'旧声音'}],shots=[{'id':'old'}],exports=[{'file':'old.mp4'}]);core.save_project(p)
            r=client.put(f'/api/projects/{pid}/script',json={'text':'新原稿','speaker':'zf_xiaoni','language':'Chinese'})
            self.assertEqual(r.status_code,200,r.text)
            for key in ('audio','segments','shots','exports'):self.assertEqual(r.json()[key],p[key])
            self.assertEqual(client.post(f'/api/projects/{pid}/jobs',json={'action':'render'}).status_code,400)
            core.ACTIVE[pid]={'cancel':False}
            try:self.assertEqual(client.put(f'/api/projects/{pid}/script',json={'text':'other'}).status_code,400)
            finally:core.ACTIVE.pop(pid,None)

    def test_new_text_job_and_resume_skip_successful_tts_and_asr(self):
        with tempfile.TemporaryDirectory() as root,patch.object(core,'PROJECTS',Path(root)):
            p=core.create_project('text');pid=p['id'];p['script']={'text':'你好','speaker':'zf_xiaoni','language':'Chinese'};core.save_project(p)
            with patch('core.threading.Thread'):
                core.start_job(pid,'all')
            def synthesize(_):
                q=core.read_project(pid);q.update(audio='done.wav',segments=[{'text':'你好'}],tts={'signature':tw.signature(**q['script'])});core.save_project(q)
            def plan(_):
                q=core.read_project(pid);q['shots']=[{'kind':'A'}];core.save_project(q)
            with patch.object(le,'synthesize',side_effect=synthesize) as tts,patch.object(core,'transcribe') as asr,patch.object(core,'plan',side_effect=plan) as planner,patch.object(core,'materials'),patch('aroll.generate'),patch.object(core,'render'):
                core.job_worker(pid,'all');core.ACTIVE[pid]={'cancel':False};core.job_worker(pid,'all')
                self.assertEqual(tts.call_count,1);self.assertEqual(planner.call_count,1);asr.assert_not_called()

    def test_bad_voice_empty_text_and_model_truncation_rejected(self):
        for value in ({'text':''},{'text':'x'*20001},{'text':'hi','provider':'evil'},{'text':'hi','speed':3}):
            with self.assertRaises(ValueError):le.validate_script(value)
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root);(folder/'model').write_bytes(b'x')
            (folder/'installed.json').write_text(json.dumps({'revision':'rev','files':[{'file':'model','size':2}]}))
            self.assertFalse(le.model_ready(folder,'rev'))

    def test_deepseek_json_disables_thinking_and_preserves_config(self):
        cfg={'llm_base_url':'https://api.deepseek.com','llm_model':'deepseek-v4-flash','llm_api_key':'token'}
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
