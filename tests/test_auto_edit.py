import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auto_edit
import core


class AutoEditPlanTests(unittest.TestCase):
    def project(self):
        return {
            'id':'project','name':'测试精剪','audio':'assets/audio.wav','duration':8.0,
            'bgm':None,
            'options':{
                'auto_edit_remove_pauses':True,'auto_edit_pause_threshold':.65,
                'auto_edit_pause_padding':.08,'auto_edit_highlights':True,
                'auto_edit_cards':True,'bgm_enabled':False,'bgm_volume':.14,
            },
            'segments':[
                {'start':0,'end':2,'text':'今天讨论人工智能。'},
                {'start':3.2,'end':5.2,'text':'市场正在快速变化。'},
                {'start':5.2,'end':8,'text':'这是最后的结论。'},
            ],
            'captions':[
                {'start':0,'end':2,'text':'今天讨论人工智能'},
                {'start':3.2,'end':5.2,'text':'市场正在快速变化'},
                {'start':5.2,'end':8,'text':'这是最后的结论'},
            ],
            'narrative_segments':[
                {'start':0,'end':2,'text':'今天讨论人工智能。','semantic_type':'hook','importance':'high','visual_value':1},
                {'start':3.2,'end':5.2,'text':'市场正在快速变化。','semantic_type':'data','importance':'high','visual_value':4},
            ],
            'shots':[
                {'id':'a1','kind':'A','start':0,'end':3.2,'title':'人工智能','text':'今天讨论人工智能。',
                 'keywords':['人工智能'],'media_start':0},
                {'id':'b1','kind':'B','start':3.2,'end':8,'title':'市场','text':'市场正在快速变化。',
                 'keywords':['市场'],'media_start':0},
            ],
        }

    def test_long_pause_is_removed_and_all_tracks_are_remapped(self):
        plan=auto_edit.build_edit_plan(self.project(),[{'start':2.0,'end':3.2}])
        self.assertEqual(plan['remove_ranges'],[{'start':2.08,'end':3.12,'reason':'long_pause'}])
        self.assertAlmostEqual(plan['output_duration'],6.96)
        self.assertEqual(
            [(item['output_start'],item['output_end']) for item in plan['visual_segments']],
            [(0.0,2.08),(2.08,2.16),(2.16,6.96)])
        self.assertEqual(plan['captions'][0]['highlight'],['人工智能'])
        self.assertEqual(plan['captions'][1]['start'],2.16)
        self.assertTrue(any(card['type']=='title' for card in plan['overlays']))
        auto_edit.validate_edit_plan(plan)

    def test_short_pause_is_preserved(self):
        plan=auto_edit.build_edit_plan(self.project(),[{'start':2.0,'end':2.5}])
        self.assertEqual(plan['remove_ranges'],[])
        self.assertEqual(plan['output_duration'],8.0)

    def test_caption_across_a_removed_pause_is_one_readable_cue(self):
        # A caption spanning a removed pause used to be emitted twice, with a
        # sub-frame sliver of the whole line flashing first. Removed pauses are
        # contiguous in output time, so it is still one line on screen.
        project=self.project()
        project['captions']=[{'start':0,'end':3.2,'text':'今天讨论人工智能'}]
        plan=auto_edit.build_edit_plan(project,[{'start':2.0,'end':3.2}])
        captions=plan['captions']
        texts=[caption['text'] for caption in captions]
        self.assertEqual(len(texts),len(set(texts)),'同一句字幕不能连续出现两次')
        self.assertEqual(texts,['今天讨论人工智能'])
        for caption in captions:
            self.assertGreaterEqual(caption['end']-caption['start'],.3,'不能留下看不清的闪帧字幕')
        self.assertAlmostEqual(captions[0]['start'],0.0)
        self.assertAlmostEqual(captions[0]['end'],2.16)
        auto_edit.validate_edit_plan(plan)

    def test_narrow_pause_cut_keeps_visual_timeline_contiguous(self):
        project=self.project()
        project['options']['auto_edit_pause_threshold']=.1
        project['options']['auto_edit_pause_padding']=0
        project['shots']=[
            {'id':'a1','kind':'A','start':0,'end':2.99,'title':'人工智能','text':'今天讨论人工智能。',
             'keywords':['人工智能'],'media_start':0},
            {'id':'b1','kind':'B','start':2.99,'end':8,'title':'市场','text':'市场正在快速变化。',
             'keywords':['市场'],'media_start':0},
        ]
        plan=auto_edit.build_edit_plan(project,[{'start':3.003,'end':3.2}])
        self.assertEqual(
            [(item['output_start'],item['output_end']) for item in plan['visual_segments']],
            [(0.0,2.99),(2.99,3.003),(3.003,7.803)])
        auto_edit.validate_edit_plan(plan)

    def test_chinese_semantic_keyword_maps_to_phrase_inside_caption(self):
        project=self.project()
        project['shots'][0]['keywords']=['巨大质数相乘']
        project['shots'][0]['text']='计算机找两个巨大的质数并把它们相乘。'
        project['captions'][0]['text']='计算机找两个巨大的质数并把它们相乘'
        plan=auto_edit.build_edit_plan(project,[])
        self.assertEqual(plan['captions'][0]['highlight'],['巨大','质数'])

    def test_cards_keep_semantic_timing_and_skip_hook_repetition(self):
        project=self.project()
        project['name']='B12'
        project['narrative_segments']=[
            {'start':0,'end':2,'text':'每天都在使用密码。','semantic_type':'hook','importance':'high','visual_value':4},
            {'start':3.2,'end':5.2,'text':'超级计算机也需要几万年。','semantic_type':'data','importance':'high','visual_value':4,
             'visual_subject':'超级计算机'},
            {'start':5.2,'end':8,'text':'安全来自计算的不对称。','semantic_type':'opinion','importance':'high','visual_value':2},
            {'start':2,'end':3.2,'text':'这就是 RSA 非对称加密。','semantic_type':'intro','importance':'high','visual_value':2},
        ]
        cards=auto_edit.build_edit_plan(project,[])['overlays']
        self.assertEqual(cards[0]['text'],'这就是 RSA 非对称加密。')
        self.assertEqual([card['text'] for card in cards[1:]],
                         ['超级计算机\n几万年'])
        self.assertEqual(cards[1]['label'],'关键数据')
        self.assertFalse(any('密码' in card['text'] for card in cards[1:]))
        self.assertGreaterEqual(cards[1]['start'],3.2)

    def test_signature_changes_with_timeline_or_audio_policy(self):
        project=self.project();before=auto_edit.plan_signature(project)
        changed=copy.deepcopy(project);changed['shots'][0]['end']=3.1
        self.assertNotEqual(before,auto_edit.plan_signature(changed))
        changed=copy.deepcopy(project);changed['options']['bgm_enabled']=True;changed['bgm']='assets/music.m4a'
        self.assertNotEqual(before,auto_edit.plan_signature(changed))

    def test_validator_rejects_output_gaps(self):
        plan=auto_edit.build_edit_plan(self.project(),[])
        plan['visual_segments'][1]['output_start']+=.2
        with self.assertRaisesRegex(ValueError,'空隙'):
            auto_edit.validate_edit_plan(plan)

    def test_real_export_applies_edit_plan_cards_subtitles_and_bgm(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(core,'PROJECTS',Path(directory)):
            project=core.create_project('真实精剪导出');folder=core.project_dir(project['id'])
            image=folder/'assets'/'visual.jpg';core.Image.new('RGB',(96,54),'#315747').save(image)
            audio=folder/'assets'/'audio.wav'
            core.run([
                core.FFMPEG,'-y','-v','error',
                '-f','lavfi','-i','sine=frequency=440:duration=0.4:sample_rate=48000',
                '-f','lavfi','-i','anullsrc=r=48000:cl=stereo:d=1',
                '-f','lavfi','-i','sine=frequency=660:duration=0.4:sample_rate=48000',
                '-filter_complex','[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]',
                '-map','[out]','-ar','48000','-ac','2','-c:a','pcm_s16le',audio])
            bgm=folder/'assets'/'music.m4a'
            core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i',
                      'sine=frequency=220:duration=2:sample_rate=48000',
                      '-c:a','aac','-b:a','128k',bgm])
            duration=round(core.probe(audio)['duration'],3)
            project.update(
                audio='assets/audio.wav',duration=duration,bgm='assets/music.m4a',bgm_name='music.m4a',
                segments=[{'id':0,'start':0,'end':.4,'text':'自动精剪开始。'},
                          {'id':1,'start':1.4,'end':duration,'text':'自动精剪结束。'}],
                candidate_segments=[],narrative_segments=[],
                shots=[{'id':'b1','kind':'B','start':0,'end':duration,'title':'自动精剪',
                        'text':'自动精剪开始。自动精剪结束。','keywords':['自动精剪'],
                        'asset':'assets/visual.jpg','media_start':0,'source':{'provider':'test'}}],
                job={'status':'running','stage':'test','progress':0,'message':''})
            project['options'].update(
                resolution='720p',subtitles=True,auto_edit_enabled=True,
                auto_edit_pause_threshold=.65,auto_edit_pause_padding=.08,
                auto_edit_highlights=True,auto_edit_cards=True,
                bgm_enabled=True,bgm_volume=.14)
            enriched=copy.deepcopy(project);enriched['captions']=core.subtitle_events(project)
            project['edit_plan']=auto_edit.build_edit_plan(enriched,[{'start':.4,'end':1.4}])
            core.save_project(project);core.render(project['id'])
            saved=core.read_project(project['id']);record=saved['exports'][-1]
            output=folder/record['file'];info=core.probe(output)
            self.assertTrue(record['auto_edit']);self.assertTrue(record['bgm'])
            self.assertAlmostEqual(info['duration'],project['edit_plan']['output_duration'],delta=.18)
            video=next(stream for stream in info['streams'] if stream['codec_type']=='video')
            self.assertEqual((video['width'],video['height']),(1280,720))
            self.assertTrue(any(stream['codec_type']=='audio' for stream in info['streams']))
            export=output.parent
            self.assertTrue((export/'edit-plan.json').is_file())
            self.assertIn('自动精剪', (export/'subtitles.ass').read_text(encoding='utf-8'))
            manifest=json.loads((export/'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['edit_plan'],'edit-plan.json')


if __name__=='__main__':
    unittest.main()
