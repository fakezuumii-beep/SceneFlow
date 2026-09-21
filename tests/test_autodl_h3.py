import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import core
from PIL import Image
from providers.aroll import get_aroll_provider
from providers.aroll import autodl_h3


class AutoDLH3Tests(unittest.TestCase):
    def provider(self, **values):
        settings = {'aroll_provider': 'autodl_h3', 'aroll_autodl_api_key': 'token-1234567890',
                    'aroll_autodl_resolution': '768p横'}
        settings.update(values)
        return get_aroll_provider(settings)

    def test_config_and_status_do_not_make_a_paid_request(self):
        provider = self.provider()
        with patch.object(autodl_h3.requests, 'post') as post, patch.object(autodl_h3.requests, 'get') as get:
            result = provider.test_connection()
        self.assertTrue(result['ok'])
        self.assertTrue(provider.status()['ready'])
        post.assert_not_called()
        get.assert_not_called()

    def test_exact_workflow_payload_and_raw_authorization_header(self):
        response = Mock(status_code=200)
        response.json.return_value = {'code': 'Success', 'data': {'task_id': 'paid-task', 'status': 'QUEUED'}}
        with patch.object(autodl_h3.requests, 'post', return_value=response) as post:
            data = autodl_h3._submit(self.provider(), {
                'resolution': '768p横', 'ref_audio_0': 'data:audio/wav;base64,AA==',
                'ref_image_0': 'data:image/jpeg;base64,AA==', 'duration': 5,
                'prompt':autodl_h3.H3_PROMPTS['steady'],
            })
        self.assertEqual(data['task_id'], 'paid-task')
        args, kwargs = post.call_args
        self.assertEqual(args[0], autodl_h3.API_BASE + '/' + autodl_h3.WORKFLOW_ID)
        self.assertEqual(kwargs['headers']['Authorization'], 'token-1234567890')
        self.assertEqual(set(kwargs['json']), {
            'resolution', 'ref_audio_0', 'ref_image_0', 'duration','prompt'})
        self.assertIsInstance(kwargs['json']['duration'], int)
        self.assertIn('不要切镜',kwargs['json']['prompt'])

    def test_dedicated_automatic_lipsync_workflow_and_all_resolutions(self):
        provider = self.provider()
        self.assertEqual(autodl_h3.WORKFLOW_ID, 'minimax_h3_image_audio_to_video_v2_15s')
        self.assertEqual(provider.cache_identity()['workflow_hash'], autodl_h3.WORKFLOW_ID)
        self.assertEqual(autodl_h3.RESOLUTIONS,{
            '480p竖':(480,832),'768p竖':(768,1344),'1080p竖':(1080,1920),
            '480p横':(832,480),'768p横':(1344,768),'1080p横':(1920,1080)})
        for resolution in autodl_h3.RESOLUTIONS:
            self.assertTrue(self.provider(aroll_autodl_resolution=resolution).validate_config())
        self.assertEqual(autodl_h3.CLOUD_RESOLUTION['1080p横'],'768p横')
        with self.assertRaisesRegex(ValueError, '支持'):
            self.provider(aroll_autodl_resolution='4k横').validate_config()

    def test_api_duration_uses_whole_seconds_without_exceeding_limit(self):
        self.assertEqual(autodl_h3._api_duration(0.04), 1)
        self.assertEqual(autodl_h3._api_duration(7.04), 8)
        self.assertEqual(autodl_h3._api_duration(15.0), 15)

    def test_paid_queue_is_bounded_to_six_workers(self):
        active = 0
        peak = 0
        lock = threading.Lock()

        def worker(value):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(.03)
            with lock:
                active -= 1
            return value

        results, errors, scheduled = autodl_h3._run_bounded(
            range(12), worker, autodl_h3.MAX_CONCURRENCY)
        self.assertEqual(peak, 6)
        self.assertEqual(scheduled, 12)
        self.assertEqual(sorted(results.values()), list(range(12)))
        self.assertEqual(errors, [])

    def test_paid_queue_stops_scheduling_after_first_error(self):
        started = []
        lock = threading.Lock()

        def worker(value):
            with lock:
                started.append(value)
            if value == 0:
                raise RuntimeError('paid task failed')
            time.sleep(.03)
            return value

        results, errors, scheduled = autodl_h3._run_bounded(range(8), worker, 2)
        self.assertEqual(set(started), {0, 1})
        self.assertEqual(scheduled, 2)
        self.assertEqual(results, {1: 1})
        self.assertEqual(str(errors[0][1]), 'paid task failed')

    def test_completed_task_without_url_is_kept_for_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder)
            core.atomic_json(cache / 'task.json', {'task_id': 'keep-me', 'status': 'QUEUED', 'attempt': 1})
            with patch.object(autodl_h3, '_query', return_value={'status': 'SUCCESS', 'results': []}), \
                 patch.object(autodl_h3, 'POLL_SECONDS', 0), patch.object(autodl_h3, 'POLL_TIMEOUT', 2):
                with self.assertRaisesRegex(RuntimeError, '任务号已保留'):
                    autodl_h3._collect(self.provider(), 'p', cache, {}, 0, 1)
            state = json.loads((cache / 'task.json').read_text(encoding='utf-8'))
            self.assertEqual(state['task_id'], 'keep-me')
            self.assertEqual(state['attempt'], 1)

    def test_long_shot_chunks_stay_under_fifteen_seconds(self):
        chunks = autodl_h3._frame_chunks(round(31.2 * autodl_h3.FPS))
        self.assertEqual(sum(chunks), round(31.2 * autodl_h3.FPS))
        self.assertTrue(all(25 <= frames <= 15 * autodl_h3.FPS for frames in chunks))

    def test_fifteen_seconds_stays_one_h3_task_and_over_limit_hard_splits(self):
        self.assertEqual(autodl_h3._frame_chunks(15 * autodl_h3.FPS),[15 * autodl_h3.FPS])
        chunks=autodl_h3._frame_chunks(15 * autodl_h3.FPS + 1)
        self.assertEqual(len(chunks),2)
        self.assertEqual(sum(chunks),15 * autodl_h3.FPS + 1)

    def test_existing_adjacent_aroll_is_collapsed_before_h3_submission(self):
        project={'duration':18,'segments':[
            {'id':0,'start':0,'end':4,'text':'第一句。'},
            {'id':1,'start':4,'end':9,'text':'第二句。'},
            {'id':2,'start':9,'end':18,'text':'第三句。'},
        ],'shots':[
            {'id':'a1','kind':'A','start':0,'end':4,'from':0,'to':0,'text':'第一句。',
             'narrative_ids':['n1'],'camera':'medium','motion':None,'visual_change':'hold',
             'aroll_asset':'assets/old-1.mp4','aroll_signature':'old-1'},
            {'id':'a2','kind':'A','start':4,'end':9,'from':1,'to':1,'text':'第二句。',
             'narrative_ids':['n2'],'camera':'medium_close','motion':None,'visual_change':'cut_in',
             'aroll_asset':'assets/old-2.mp4','aroll_signature':'old-2'},
            {'id':'b1','kind':'B','start':9,'end':12},
            {'id':'a3','kind':'A','start':12,'end':18,'from':2,'to':2,'text':'第三句。',
             'narrative_ids':['n3'],'camera':'close','motion':None,'visual_change':'cut_in'},
        ]}
        changed,id_map=autodl_h3._collapse_aroll_runs(project)
        self.assertTrue(changed)
        self.assertEqual([shot['id'] for shot in project['shots']],['a1','b1','a3'])
        merged=project['shots'][0]
        self.assertEqual((merged['start'],merged['end'],merged['text']),(0,9,'第一句。第二句。'))
        self.assertEqual(merged['visual_change'],'h3_native')
        self.assertEqual(merged['aroll_edit_mode'],'provider_native')
        self.assertIsNone(merged['camera'])
        self.assertEqual(id_map['a2'],'a1')
        self.assertEqual(len(merged['aroll_history']),2)
        self.assertFalse(autodl_h3._collapse_aroll_runs(project)[0])

    def test_existing_single_h3_asset_is_reused_when_only_crop_metadata_changes(self):
        shot={'id':'a1','kind':'A','start':0,'end':8,'from':0,'to':0,'text':'完整一段。',
              'narrative_ids':['n1'],'camera':'medium_close','motion':None,'visual_change':'cut_in',
              'aroll_asset':'assets/h3.mp4','aroll_signature':'same',
              'aroll_provenance':{'provider':'autodl_h3'}}
        project={'duration':8,'segments':[{'id':0,'start':0,'end':8,'text':'完整一段。'}],
                 'shots':[shot]}
        changed,_=autodl_h3._collapse_aroll_runs(project)
        self.assertTrue(changed)
        self.assertEqual(project['shots'][0]['aroll_asset'],'assets/h3.mp4')
        self.assertEqual(project['shots'][0]['aroll_signature'],'same')
        self.assertEqual(project['shots'][0]['visual_change'],'h3_native')
        self.assertIsNone(project['shots'][0]['camera'])

    def test_adjacent_aroll_with_different_shot_overrides_stays_separate(self):
        project={'duration':8,'segments':[
            {'id':0,'start':0,'end':4,'text':'第一段。'},{'id':1,'start':4,'end':8,'text':'第二段。'}],
            'shots':[
                {'id':'a1','kind':'A','start':0,'end':4,'from':0,'to':0,'text':'第一段。','camera':'medium','motion':None,'visual_change':'hold','aroll_config':{'provider':'autodl_h3','prompt':'calm'}},
                {'id':'a2','kind':'A','start':4,'end':8,'from':1,'to':1,'text':'第二段。','camera':'close','motion':None,'visual_change':'cut_in','aroll_config':{'provider':'autodl_h3','prompt':'serious'}},
            ]}
        changed,_=autodl_h3._collapse_aroll_runs(project)
        self.assertTrue(changed)
        self.assertEqual([shot['id'] for shot in project['shots']],['a1','a2'])
        self.assertEqual([shot['aroll_config']['prompt'] for shot in project['shots']],['calm','serious'])

    def test_signature_is_shot_local_not_adjacent_run_wide(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'PROJECTS', Path(folder)), \
             patch.object(core, 'DEFAULT_LOOP_VIDEO', Path(folder) / 'missing.mp4'):
            project = core.create_project('h3-signature')
            root = core.project_dir(project['id'])
            audio = root / 'assets' / 'audio.wav'
            audio.write_bytes(b'RIFF' + b'\0' * 128)
            image = root / 'assets' / 'host.jpg'
            image.write_bytes(b'jpeg')
            project.update(audio='assets/audio.wav', portrait='assets/host.jpg')
            first = {'id': 'a1', 'kind': 'A', 'start': 0, 'end': 4}
            second = {'id': 'a2', 'kind': 'A', 'start': 4, 'end': 8}
            project['shots'] = [first, second]
            provider = self.provider()
            signature = provider.signature(project, first)
            second['end'] = 9
            self.assertEqual(signature, provider.signature(project, first))

    def test_local_pipeline_promotes_only_a_valid_silent_asset(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'PROJECTS', Path(folder)), \
             patch.object(core, 'DEFAULT_LOOP_VIDEO', Path(folder) / 'missing.mp4'):
            project = core.create_project('h3-local-pipeline')
            root = core.project_dir(project['id'])
            audio = root / 'assets' / 'audio.wav'
            core.run([core.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i',
                      'sine=frequency=440:duration=1', '-ac', '1', '-ar', '24000', audio])
            image = root / 'assets' / 'host.jpg'
            Image.new('RGB', (320, 180), '#56786a').save(image)
            shot = {'id': 'a1', 'kind': 'A', 'start': 0.0, 'end': 1.0, 'title': 'host'}
            project.update(audio='assets/audio.wav', portrait='assets/host.jpg',
                           portrait_name='host.jpg', duration=1.0, shots=[shot])
            project['job'] = {'status': 'running', 'stage': '', 'progress': 0, 'message': ''}
            core.save_project(project)
            raw = root / 'synthetic-h3.mp4'
            core.run([core.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi', '-i',
                      'color=c=green:s=320x180:r=25:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', raw])
            provider = self.provider(aroll_autodl_resolution='480p横')
            with patch.dict(core.ACTIVE, {project['id']: {'cancel': False}}), \
                 patch.object(autodl_h3, '_collect', return_value=raw) as collect:
                provider.generate(project['id'])
            saved = core.read_project(project['id'])['shots'][0]
            asset = root / saved['aroll_asset']
            info = core.probe(asset)
            self.assertTrue(provider.is_ready(core.read_project(project['id']), saved))
            self.assertEqual(next(s for s in info['streams'] if s['codec_type'] == 'video')['nb_frames'], '25')
            self.assertFalse(any(s['codec_type'] == 'audio' for s in info['streams']))
            submitted = collect.call_args.args[3]
            self.assertEqual(submitted['duration'], 1)
            self.assertNotIn('audio_duration', submitted)
            self.assertIn('不要切镜',submitted['prompt'])
            self.assertEqual(saved['aroll_provenance']['workflow_id'], autodl_h3.WORKFLOW_ID)
            self.assertEqual(saved['aroll_provenance']['concurrency_limit'], 6)
            self.assertEqual(saved['aroll_provenance']['continuity_policy'],
                             'same-reference-background-across-native-cuts-v1')
            self.assertEqual(saved['aroll_provenance']['prompt_policy'],'stable-podcast-camera-v1')
            self.assertNotIn('api_key', json.dumps(saved, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
