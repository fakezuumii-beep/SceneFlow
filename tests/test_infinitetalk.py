import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,Mock
import core
import aroll
from providers.aroll import get_aroll_provider
from providers.aroll.infinitetalk import InfiniteTalkProvider


class InfiniteTalkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.private=Path(self.temp.name)
        self.patch=patch.object(core,'PRIVATE',self.private);self.patch.start();self.addCleanup(self.patch.stop)
        self.graph={'1':{'class_type':'LoadImage','inputs':{'image':'original.png'}},
                    '2':{'class_type':'LoadAudio','inputs':{'audio':'original.wav'}},
                    '3':{'class_type':'MultiTalkWav2VecEmbeds','inputs':{'audio_1':['2',0],'num_frames':500,'fps':24}},
                    '4':{'class_type':'VHS_VideoCombine','inputs':{'frame_rate':25}},
                    '5':{'class_type':'INTConstant','inputs':{'value':832}},
                    '6':{'class_type':'INTConstant','inputs':{'value':480}},
                    '7':{'class_type':'ImageResizeKJv2','inputs':{'image':['1',0],'width':['5',0],'height':['6',0]}},
                    '8':{'class_type':'WanVideoTextEncodeCached','inputs':{
                        'positive_prompt':'default positive','negative_prompt':'default negative'}}}
        self.path=self.private/'graph.json';self.path.write_text(json.dumps(self.graph))
        self.cfg={'aroll_provider':'infinitetalk','aroll_comfyui_url':'http://127.0.0.1:8188','aroll_comfyui_workflow':'graph.json',
                  'aroll_comfyui_workflow_hash':'original','aroll_person_node':'1','aroll_audio_node':'2','aroll_output_node':'4'}
        self.provider=get_aroll_provider(self.cfg)

    def test_audio_clock_and_duration_override_without_mutating_original(self):
        self.provider.validate_config()
        graph=self.provider.build_prompt('new.png','new.wav',801,'SOLO/test')
        self.assertEqual(graph['3']['inputs']['fps'],25)
        self.assertEqual(graph['3']['inputs']['num_frames'],801)
        self.assertEqual(graph['4']['inputs']['frame_rate'],25)
        self.assertEqual(graph['1']['inputs']['image'],'new.png')
        self.assertEqual(graph['2']['inputs']['audio'],'new.wav')
        self.assertEqual(json.loads(self.path.read_text()),self.graph)

    def test_rejects_more_than_the_workflow_frame_limit(self):
        with self.assertRaisesRegex(ValueError,'10000'):
            self.provider.build_prompt('new.png','new.wav',10001,'SOLO/test')

    def test_square_project_uses_native_short_side_without_mutating_workflow(self):
        graph=self.provider.build_prompt('new.png','new.wav',801,'SOLO/test','1:1')
        self.assertEqual(graph['5']['inputs']['value'],480)
        self.assertEqual(graph['6']['inputs']['value'],480)
        self.assertEqual(json.loads(self.path.read_text()),self.graph)

    def test_portrait_project_uses_native_vertical_size_without_mutating_workflow(self):
        graph=self.provider.build_prompt('new.png','new.wav',801,'SOLO/test','9:16')
        self.assertEqual(graph['5']['inputs']['value'],480)
        self.assertEqual(graph['6']['inputs']['value'],832)
        self.assertEqual(json.loads(self.path.read_text()),self.graph)

    def test_square_project_rejects_workflow_without_adjustable_host_resize(self):
        del self.graph['7'];self.path.write_text(json.dumps(self.graph))
        with self.assertRaisesRegex(ValueError,'ImageResize'):
            self.provider.build_prompt('new.png','new.wav',100,'SOLO/test','1:1')

    def test_actual_graph_changes_invalidate_cache(self):
        before=self.provider.cache_identity()
        self.graph['3']['inputs']['audio_scale']=.9;self.path.write_text(json.dumps(self.graph))
        self.assertNotEqual(before,self.provider.cache_identity())

    def test_prompt_defaults_and_overrides_do_not_mutate_original_workflow(self):
        self.assertEqual(self.provider.prompt_defaults(),{
            'positive_prompt':'default positive','negative_prompt':'default negative'})
        baseline=self.provider.cache_identity()
        self.assertNotIn('prompt_override_hash',baseline)
        self.provider.settings['aroll_infinitetalk_positive_prompt']='custom positive'
        self.provider.settings['aroll_infinitetalk_negative_prompt']='custom negative'
        changed=self.provider.cache_identity()
        self.assertIn('prompt_override_hash',changed)
        graph=self.provider.build_prompt('new.png','new.wav',101,'SOLO/test')
        self.assertEqual(graph['8']['inputs']['positive_prompt'],'custom positive')
        self.assertEqual(graph['8']['inputs']['negative_prompt'],'custom negative')
        self.assertEqual(json.loads(self.path.read_text()),self.graph)

    def test_different_shot_prompts_split_adjacent_infinite_runs(self):
        shots=[
            {'id':'a1','kind':'A','start':0,'end':1,'aroll_config':{}},
            {'id':'a2','kind':'A','start':1,'end':2,'aroll_config':{}},
            {'id':'a3','kind':'A','start':2,'end':3,'aroll_config':{'positive_prompt':'closer framing'}},
        ]
        runs=aroll.contiguous_runs(shots,self.provider.run_config_key)
        self.assertEqual([[shot['id'] for shot in run] for run in runs],[['a1','a2'],['a3']])

    def test_project_aspect_ratio_is_part_of_generation_identity(self):
        landscape=self.provider.project_cache_identity({'options':{'aspect_ratio':'16:9'}})
        square=self.provider.project_cache_identity({'options':{'aspect_ratio':'1:1'}})
        portrait=self.provider.project_cache_identity({'options':{'aspect_ratio':'9:16'}})
        self.assertNotEqual(landscape,square)
        self.assertNotEqual(landscape,portrait)
        self.assertNotEqual(square,portrait)
        self.assertEqual(square['aspect_ratio'],'1:1')
        self.assertEqual(portrait['aspect_ratio'],'9:16')

    def test_rejects_canvas_and_dual_speaker_graph(self):
        self.graph['3']['inputs']['audio_2']=['2',0];self.path.write_text(json.dumps(self.graph))
        with self.assertRaisesRegex(ValueError,'一条音轨'):self.provider.validate_config()
        self.path.write_text(json.dumps({'nodes':[]}))
        self.assertFalse(self.provider.status()['ready'])

    def test_private_workflow_cannot_escape_directory(self):
        self.cfg['aroll_comfyui_workflow']='../graph.json'
        with self.assertRaises(ValueError):self.provider.workflow()

    def test_ambiguous_submission_is_not_repeated(self):
        core.atomic_json(self.private/'comfy-job.json',{'prompt_id':None})
        with patch.object(self.provider,'request') as request:
            with self.assertRaisesRegex(ValueError,'不明确'):self.provider.collect('test',self.private,{})
            request.assert_not_called()

    def test_cancel_only_deletes_owned_queued_job(self):
        core.atomic_json(self.private/'comfy-job.json',{'prompt_id':'owned'})
        with patch.dict(core.ACTIVE,{'test':{'cancel':True}}),patch.object(self.provider,'request') as request:
            with self.assertRaisesRegex(RuntimeError,'停止'):self.provider.collect('test',self.private,{})
            request.assert_called_once_with('POST','/queue',json={'delete':['owned']})

    def test_failed_job_is_retryable_and_does_not_write_video(self):
        core.atomic_json(self.private/'comfy-job.json',{'prompt_id':'owned'})
        response=Mock();response.json.return_value={'owned':{'status':{'status_str':'error','messages':['OOM']}}}
        with patch.object(self.provider,'request',return_value=response):
            with self.assertRaisesRegex(RuntimeError,'OOM'):self.provider.collect('test',self.private,{})
        self.assertFalse((self.private/'comfy-job.json').exists())
        self.assertFalse((self.private/'raw.mp4').exists())


if __name__=='__main__':unittest.main()
