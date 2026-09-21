import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

import core
from motion.template_router import MotionResolver
from providers.generation.h3_scene import VIDEO_PROMPT_SUFFIX, GeneratedScenePromptBuilder, GeneratedSceneResolver
from providers.aroll import autodl_h3
from visual_director.evidence import EvidenceResolver, build_search_queries, score_candidate
from visual_director.still_motion import stable_still_filter


class FakeScreenshot:
    def capture(self, url, target):
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (900, 1200), '#d8e2e7').save(target)
        return {'path':target, 'title':'OpenAI official announcement'}


class VisualAssetResolverTests(unittest.TestCase):
    def project(self, name):
        project=core.create_project(name)
        folder=core.project_dir(project['id'])
        audio=folder/'assets'/'audio.wav'
        core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i',
                  'sine=frequency=440:duration=3','-ac','1','-ar','24000',audio])
        project.update(audio='assets/audio.wav',duration=3)
        return project,folder

    def test_evidence_query_builder_and_official_domain_score(self):
        section={
            'entities':[{'name':'OpenAI','type':'company'}],
            'evidence_target':'GPT-X official announcement',
            'text':'OpenAI发布GPT-X。',
        }
        queries=build_search_queries(section)
        self.assertTrue(any('site:openai.com' in query for query in queries))
        score,reasons=score_candidate({
            'url':'https://openai.com/index/gpt-x',
            'title':'Introducing GPT-X',
            'snippet':'OpenAI announcement',
        },section,'OpenAI GPT-X official')
        self.assertGreaterEqual(score,100)
        self.assertTrue({'official_domain','official_event_page'}.intersection(reasons))

    def test_still_motion_policy_removes_jittery_zoompan(self):
        filters=stable_still_filter(1080,1920,30,.12)
        self.assertNotIn('zoompan',filters)
        self.assertIn('scale=1080:1920',filters)
        self.assertIn('crop=1080:1920',filters)
        self.assertIn('fade=t=in',filters)

    def test_evidence_slices_frame_different_regions_of_a_reused_page(self):
        from visual_director.evidence import part_window
        for size in ((1440, 6000), (1440, 1800), (900, 1200)):
            content = (0.0, 0.60)
            windows = [part_window(size, (720, 1280), part, 5, None, content)
                       for part in range(1, 6)]
            framings = {(round(window['y'], 4), round(window['width'], 4),
                         round(window['height'], 4)) for window in windows}
            self.assertEqual(len(framings), 5, f'{size} 的每一片取景必须不同：{framings}')
            for window in windows:
                # 每一片都必须落在文章开头之内，不能翻到付费墙/尾部
                self.assertLessEqual(window['y'] + window['height'], content[1] + 1e-6, size)
                self.assertLessEqual(window['width'], 1.0, size)
                # 文字至少比整页缩略大一倍
                self.assertLessEqual(window['width'], 0.62, size)

    def test_evidence_clip_is_a_hard_cut_not_a_fade_from_black(self):
        from PIL import ImageStat
        from visual_director.evidence import EvidencePresenter
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            still=folder/'still.png'
            Image.new('RGB',(360,640),'#e8e6e2').save(still)
            clip=folder/'clip.mp4'
            EvidencePresenter((360,640)).clip(still,clip,1.0)
            first=folder/'first.png'
            core.run([core.FFMPEG,'-y','-v','error','-i',str(clip),'-frames:v','1',str(first)])
            mean=ImageStat.Stat(Image.open(first).convert('L')).mean[0]
            self.assertGreater(mean,180,'证据镜头是硬切，不能从黑场淡入')

    def test_evidence_resolver_captures_and_renders_unified_clip(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'PROJECTS',Path(folder)):
            project,root=self.project('evidence')
            shot={'id':'e1','kind':'B','visual_role':'E','start':0.0,'end':1.0,
                  'text':'OpenAI发布新模型。','title':'OpenAI证据',
                  'visual_segment_id':'S001','entities':[{'name':'OpenAI','type':'company'}],
                  'evidence_target':'OpenAI official announcement',
                  'search_query':'OpenAI official announcement','fallback':'A'}
            project['shots']=[shot]
            core.save_project(project)
            with patch('visual_director.evidence.search_web',return_value=[{
                'url':'https://openai.com/index/gpt-x',
                'title':'OpenAI GPT-X official announcement',
                'snippet':'OpenAI GPT-X announcement',
                'provider':'test',
            }]):
                result=EvidenceResolver(FakeScreenshot()).resolve(
                    project,shot,(320,320),project['options'])
            self.assertEqual(result['status'],'ready')
            self.assertEqual(result['asset_type'],'video')
            clip=root/result['asset_path']
            self.assertTrue(clip.is_file())
            self.assertGreater(core.probe(clip)['duration'],.8)
            self.assertEqual(result['metadata']['resolver'],'evidence')
            self.assertIn('openai.com',result['source'])

    def test_motion_resolver_produces_real_timeline_clip(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'PROJECTS',Path(folder)):
            project,root=self.project('motion')
            shot={'id':'m1','kind':'B','visual_role':'M','start':0.0,'end':1.0,
                  'text':'价格从15美元下降到10美元。','title':'API价格',
                  'visual_segment_id':'S001','motion_type':'M_COMPARE',
                  'motion_data':{'before':'$15','after':'$10','label':'API价格'},
                  'motion_plan':{'template':'M_COMPARE','props':{
                      'title':'API价格','items':['$15','$10'],'numbers':['$15','$10'],
                      'aspect_ratio':'1:1'}}}
            project['shots']=[shot]
            core.save_project(project)
            result=MotionResolver().resolve(project,shot,(320,320),project['options'])
            clip=root/result['asset_path']
            self.assertTrue(clip.is_file())
            self.assertGreater(core.probe(clip)['duration'],.8)
            self.assertEqual(result['metadata']['template'],'M_COMPARE')

    def test_generated_scene_prompt_does_not_reuse_aroll_lipsync_policy(self):
        prompt=GeneratedScenePromptBuilder().build({
            'text':'未来每个人都有自己的AI助手。',
            'generation_concept':'现代城市中的年轻人使用个人AI助手。',
            'continuity_group':'CG01',
        })
        self.assertIn('不出现主播口播',prompt)
        self.assertIn('不要口型特写',prompt)
        self.assertIn('continuity_group=CG01',prompt)
        self.assertNotIn('口型严格跟随参考音频',prompt)
        self.assertIn('参考模式：Ref2VA',prompt)
        self.assertEqual(prompt.splitlines()[-1],VIDEO_PROMPT_SUFFIX)

    def test_generated_scene_reuses_h3_engine_with_generation_prompt(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'PROJECTS',Path(folder)), \
             patch.object(core,'DEFAULT_LOOP_VIDEO',Path(folder)/'missing.mp4'):
            project,root=self.project('generated')
            shot={'id':'g1','kind':'B','visual_role':'G','start':0.0,'end':1.0,
                  'text':'未来每个人都有自己的AI助手。','title':'未来AI助手',
                  'visual_segment_id':'S001',
                  'generation_concept':'现代城市中的年轻人使用个人AI助手。'}
            project['shots']=[shot]
            core.save_project(project)
            raw=root/'raw.mp4'
            core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i',
                      'color=c=navy:s=320x180:r=25:d=3','-c:v','libx264',
                      '-pix_fmt','yuv420p',raw])
            settings={'aroll_autodl_api_key':'token-1234567890',
                      'aroll_autodl_resolution':'480p横',
                      'aroll_autodl_cut_style':'steady'}
            with patch.dict(core.ACTIVE,{project['id']:{'cancel':False}}), \
                 patch.object(autodl_h3,'_collect',return_value=raw) as collect:
                result=GeneratedSceneResolver().resolve(settings,project,shot)
            submitted=collect.call_args.args[3]
            self.assertIn('不出现主播口播',submitted['prompt'])
            self.assertEqual(collect.call_args.args[3]['duration'],3)
            self.assertEqual(collect.call_args.args[3]['resolution'],'480p横')
            self.assertIn('seed',submitted)
            self.assertIn('ref_image_0',submitted)
            self.assertIn('ref_audio_0',submitted)
            self.assertNotIn('口型严格跟随参考音频',submitted['prompt'])
            self.assertTrue((root/result['asset_path']).is_file())
            self.assertEqual(result['metadata']['provider'],'autodl_h3')
            self.assertEqual(result['metadata']['adapter_id'],'autodl_h3_image_audio_to_video')
            self.assertNotIn('token-1234567890',json.dumps(result,ensure_ascii=False))

    def test_generated_scene_submits_original_multi_reference_payload(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'PROJECTS',Path(folder)), \
             patch.object(core,'DEFAULT_LOOP_VIDEO',Path(folder)/'missing.mp4'):
            project,root=self.project('generated-multi')
            first=root/'assets'/'reference-1.png'
            second=root/'assets'/'reference-2.png'
            Image.new('RGB',(320,180),'#315747').save(first)
            Image.new('RGB',(320,180),'#7a5f42').save(second)
            shot={'id':'g2','kind':'B','visual_role':'G','start':0.0,'end':2.0,
                  'text':'未来城市中的私人AI助手。','title':'未来AI助手',
                  'visual_segment_id':'S002',
                  'generation_concept':'一个年轻人在未来城市中使用个人AI助手。',
                  'reference_images':['assets/reference-1.png','assets/reference-2.png'],
                  'reference_audios':['assets/audio.wav']}
            project['shots']=[shot]
            core.save_project(project)
            raw=root/'raw-multi.mp4'
            core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i',
                      'color=c=purple:s=320x180:r=25:d=3','-c:v','libx264',
                      '-pix_fmt','yuv420p',raw])
            settings={'aroll_autodl_api_key':'token-1234567890',
                      'aroll_autodl_resolution':'480p横'}
            with patch.dict(core.ACTIVE,{project['id']:{'cancel':False}}), \
                 patch.object(autodl_h3,'_collect',return_value=raw) as collect:
                result=GeneratedSceneResolver().resolve(settings,project,shot)
            submitted=collect.call_args.args[3]
            self.assertIn('ref_image_0',submitted)
            self.assertIn('ref_image_1',submitted)
            self.assertNotIn('ref_image_2',submitted)
            self.assertIn('ref_audio_1',submitted)
            self.assertEqual(result['metadata']['reference_policy'],'multi_reference')
            self.assertEqual(len(result['metadata']['reference_images']),2)
            self.assertEqual(len(result['metadata']['reference_audios']),1)


if __name__=='__main__':
    unittest.main()
