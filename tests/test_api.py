import copy, io, json, sys, uuid, wave
from pathlib import Path
from unittest import TestCase, mock
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core, server

class ApiTests(TestCase):
    def test_project_aspect_ratio_can_switch_to_square_or_portrait(self):
        r=self.client.patch(f'/api/projects/{self.pid}',json={'options':{'aspect_ratio':'1:1'}})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['options']['aspect_ratio'],'1:1')
        r=self.client.patch(f'/api/projects/{self.pid}',json={'options':{'aspect_ratio':'9:16'}})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['options']['aspect_ratio'],'9:16')
        self.assertEqual(self.client.patch(f'/api/projects/{self.pid}',json={'options':{'aspect_ratio':'4:3'}}).status_code,400)

    def test_project_can_enable_two_step_mode(self):
        r=self.client.patch(f'/api/projects/{self.pid}',json={'options':{'workflow_mode':'two_step'}})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['options']['workflow_mode'],'two_step')
        self.assertEqual(self.client.patch(f'/api/projects/{self.pid}',json={'options':{'workflow_mode':'unknown'}}).status_code,400)

    def test_auto_edit_options_and_plan_endpoint_are_project_local(self):
        response=self.client.patch(f'/api/projects/{self.pid}',json={'options':{
            'auto_edit_enabled':True,'auto_edit_pause_threshold':.9,
            'auto_edit_highlights':False,'auto_edit_cards':True}})
        self.assertEqual(response.status_code,200,response.text)
        project=core.read_project(self.pid)
        project['segments']=[{'id':0,'start':0,'end':3,'text':'测试自动精剪。'}]
        project['shots']=[{'id':'a1','kind':'A','start':0,'end':3,'title':'测试','text':'测试自动精剪。',
                           'reason':'','keywords':['自动精剪'],'media_start':0}]
        core.save_project(project)
        with mock.patch.object(core,'detect_audio_silences',return_value=[{'start':1,'end':2.2}]):
            generated=self.client.post(f'/api/projects/{self.pid}/edit-plan',json={})
        self.assertEqual(generated.status_code,200,generated.text)
        self.assertGreater(generated.json()['removed_seconds'],0)
        result=self.client.get(f'/api/projects/{self.pid}/edit-plan').json()
        self.assertTrue(result['current'])
        self.assertEqual(result['plan']['schema_version'],'sceneflow-edit-plan-v2')

    def test_bgm_upload_is_normalized_and_enabled(self):
        sample=core.asset_path(self.pid,core.read_project(self.pid)['audio']).read_bytes()
        response=self.client.post(
            f'/api/projects/{self.pid}/upload',data={'kind':'bgm'},
            files={'file':('music.wav',sample,'audio/wav')})
        self.assertEqual(response.status_code,200,response.text)
        project=core.read_project(self.pid)
        self.assertEqual(project['bgm_name'],'music.wav')
        self.assertTrue(project['options']['bgm_enabled'])
        self.assertTrue(core.asset_path(self.pid,project['bgm']).is_file())

    def test_idle_project_can_change_aroll_provider_while_another_project_runs(self):
        other=self.client.post('/api/projects',json={'name':'already running'}).json()['id']
        before=core.settings(True)['aroll_provider']
        core.ACTIVE[other]={'cancel':False}
        try:
            response=self.client.patch(f'/api/projects/{self.pid}',json={'aroll_provider_id':'autodl_h3'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(core.read_project(self.pid)['aroll_provider_id'],'autodl_h3')
            self.assertEqual(core.settings(True)['aroll_provider'],before)
            status=self.client.get('/api/providers/status',params={'project_id':self.pid}).json()
            self.assertEqual(status['aroll']['id'],'autodl_h3')
        finally:
            core.ACTIVE.pop(other,None)

    def test_shot_aroll_override_is_saved_without_credentials(self):
        project=core.read_project(self.pid)
        project['shots']=[{'id':'a1','kind':'A','start':0,'end':3,'title':'host','text':'hello','reason':'','keywords':[],'media_start':0}]
        core.save_project(project)
        config={'provider':'autodl_h3','resolution':'480p横','batch_size':0}
        r=self.client.patch(f'/api/projects/{self.pid}/shots/a1',json={'aroll_config':{**config,'prompt':'ignored legacy value'}})
        self.assertEqual(r.status_code,200,r.text)
        saved=core.read_project(self.pid)['shots'][0]['aroll_config']
        self.assertEqual(saved,config)
        self.assertNotIn('prompt',saved)
        self.assertNotIn('api_key',json.dumps(saved))
        self.assertEqual(self.client.patch(f'/api/projects/{self.pid}/shots/a1',json={'aroll_config':{'provider':'bad'}}).status_code,400)

    def test_infinitetalk_shot_prompts_can_be_saved_and_cleared(self):
        project=core.read_project(self.pid)
        project['shots']=[{'id':'a1','kind':'A','start':0,'end':3,'title':'host','text':'hello','reason':'','keywords':[],'media_start':0}]
        core.save_project(project)
        url=f'/api/projects/{self.pid}/shots/a1'
        r=self.client.patch(url,json={'aroll_config':{
            'provider':'infinitetalk','positive_prompt':'  accurate lips  ','negative_prompt':' camera movement '}})
        self.assertEqual(r.status_code,200,r.text)
        saved=core.read_project(self.pid)['shots'][0]['aroll_config']
        self.assertEqual(saved['positive_prompt'],'accurate lips')
        self.assertEqual(saved['negative_prompt'],'camera movement')
        r=self.client.patch(url,json={'aroll_config':{'provider':'infinitetalk','positive_prompt':'','negative_prompt':''}})
        self.assertEqual(r.status_code,200,r.text)
        saved=core.read_project(self.pid)['shots'][0]['aroll_config']
        self.assertNotIn('positive_prompt',saved)
        self.assertNotIn('negative_prompt',saved)
        self.assertEqual(self.client.patch(url,json={'aroll_config':{
            'provider':'infinitetalk','positive_prompt':'x'*4001}}).status_code,400)

    def test_builtin_host_videos_are_available_from_the_picker(self):
        items=self.client.get('/api/host-materials').json()
        names={item['name'] for item in items}
        self.assertIn('builtin:sceneflow-host-female-loop-v1.mp4',names)
        self.assertIn('builtin:sceneflow-host-male-loop-v1.mp4',names)
        self.assertTrue(all(item.get('label') for item in items))

    def test_builtin_host_video_can_be_selected(self):
        r=self.client.post(f'/api/projects/{self.pid}/host-material',json={'name':'builtin:sceneflow-host-male-loop-v1.mp4'})
        self.assertEqual(r.status_code,200,r.text)
        p=self.client.get(f'/api/projects/{self.pid}').json()
        self.assertEqual(p['portrait_name'],'sceneflow-host-male-loop-v1.mp4')
        self.assertEqual(p['host_media_kind'],'video')

    def test_default_host_uses_the_configured_loop_video(self):
        source=self.root/'default-loop.mp4'
        core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','testsrc2=s=64x64:r=25:d=0.4',
                  '-c:v','libx264','-pix_fmt','yuv420p',source])
        with mock.patch.object(core,'DEFAULT_LOOP_VIDEO',source):
            p=self.client.get(f'/api/projects/{self.pid}').json()
            stored=core.read_project(self.pid)
            self.assertIsNone(stored['portrait'])
            self.assertEqual(p['host_media_kind'],'video')
            self.assertEqual(p['host_media_asset'],'assets/default-host-loop.mp4')
            self.assertTrue((core.project_dir(self.pid)/p['host_asset']).is_file())

    def test_host_video_upload_and_switch_back_to_image(self):
        import aroll
        source=self.root/'moving.mp4'
        core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','testsrc2=s=64x64:r=24:d=0.4',
                  '-f','lavfi','-i','sine=frequency=440:duration=0.4','-c:v','libx264','-c:a','aac','-shortest',source])
        before=core.read_project(self.pid)
        r=self.client.post(f'/api/projects/{self.pid}/upload',data={'kind':'portrait'},files={'file':('loop.mp4',source.read_bytes(),'video/mp4')})
        self.assertEqual(r.status_code,200,r.text)
        p=self.client.get(f'/api/projects/{self.pid}').json()
        self.assertEqual(p['host_media_kind'],'video');self.assertEqual(p['shots'],before['shots'])
        self.assertEqual(p['audio'],before['audio']);self.assertEqual(p['duration'],before['duration'])
        self.assertEqual(core.host_image(p).suffix,'.jpg')
        info=core.probe(core.host_media(p));self.assertFalse(any(s['codec_type']=='audio' for s in info['streams']))
        self.assertEqual(next(s for s in info['streams'] if s['codec_type']=='video')['r_frame_rate'],'25/1')
        sig=aroll.signature(p,{'start':0,'end':1})
        r=self.client.post(f'/api/projects/{self.pid}/upload',data={'kind':'portrait'},files={'file':('photo.jpg',core.host_image(p).read_bytes(),'image/jpeg')})
        self.assertEqual(r.status_code,200,r.text)
        updated=self.client.get(f'/api/projects/{self.pid}').json()
        self.assertEqual(updated['host_media_kind'],'image');self.assertIsNone(updated['portrait_poster'])
        self.assertNotEqual(sig,aroll.signature(updated,{'start':0,'end':1}))
        self.assertTrue(core.host_media(p).exists())

    def test_local_host_material_rejects_paths_outside_library(self):
        r=self.client.post(f'/api/projects/{self.pid}/host-material',json={'name':'../server.py'})
        self.assertEqual(r.status_code,400)

    def test_health_detects_backend_update(self):
        self.assertFalse(self.client.get('/api/health').json()['update_required'])
        with mock.patch.object(core,'code_revision',return_value='changed'):
            self.assertTrue(self.client.get('/api/health').json()['update_required'])

    def test_tts_catalog_reports_azure_v1_as_default(self):
        with mock.patch('voice_tts.requests.get',side_effect=OSError('offline')):
            result=self.client.get('/api/local-models').json()
        self.assertEqual(result['tts']['provider'],'azure-v1')
        self.assertEqual(result['tts']['name'],'Azure TTS V1')
        self.assertIn('seed-audio',result['providers'])
        self.assertIn('indextts25',result['providers'])
        self.assertIn('zh-CN-XiaoxiaoNeural',result['azure_voices']['Chinese'])

    def test_voice_reference_upload_is_normalized_without_replacing_episode_audio(self):
        before=core.read_project(self.pid)
        sample=core.asset_path(self.pid,before['audio']).read_bytes()
        response=self.client.post(f'/api/projects/{self.pid}/upload',data={'kind':'voice_reference'},
                                  files={'file':('my-voice.wav',sample,'audio/wav')})
        self.assertEqual(response.status_code,200,response.text)
        project=response.json()
        self.assertEqual(project['audio'],before['audio'])
        self.assertEqual(project['duration'],before['duration'])
        self.assertEqual(project['voice_reference_name'],'my-voice.wav')
        reference=core.asset_path(self.pid,project['voice_reference'])
        info=core.probe(reference)
        stream=next(item for item in info['streams'] if item['codec_type']=='audio')
        self.assertEqual(stream['sample_rate'],'24000')
        self.assertEqual(stream['channels'],1)

    def test_uploaded_reference_becomes_authoritative_for_index_script(self):
        body={'text':'你好，这是本地配音。','provider':'indextts25','speaker':'index-reference',
              'language':'Chinese','speed':1,'reference':''}
        self.assertEqual(self.client.put(f'/api/projects/{self.pid}/script',json=body).status_code,200)
        sample=core.asset_path(self.pid,core.read_project(self.pid)['audio']).read_bytes()
        response=self.client.post(f'/api/projects/{self.pid}/upload',data={'kind':'voice_reference'},
                                  files={'file':('index-ref.wav',sample,'audio/wav')})
        self.assertEqual(response.status_code,200,response.text)
        project=core.read_project(self.pid)
        self.assertEqual(project['script']['reference'],project['voice_reference'])
        # The point is that the uploaded reference satisfies the index script.
        # Whether a local engine is actually running is not part of this test.
        with mock.patch('local_engines.provider_status',return_value={'ready':True}):
            issues=core.generation_preflight(project,'draft')['issues']
        self.assertTrue(all(issue['code']!='tts' for issue in issues),issues)

    def test_new_project_inherits_previous_project_settings_and_voice_assets(self):
        self.client.patch(f'/api/projects/{self.pid}',json={'options':{
            'aspect_ratio':'9:16','resolution':'720p','subtitles':False,
            'auto_edit_enabled':False,'auto_edit_pause_threshold':1.2}})
        body={'text':'上期文稿','provider':'indextts25','speaker':'index-reference',
              'language':'Chinese','speed':1.1,'reference':''}
        self.client.put(f'/api/projects/{self.pid}/script',json=body)
        sample=core.asset_path(self.pid,core.read_project(self.pid)['audio']).read_bytes()
        self.client.post(f'/api/projects/{self.pid}/upload',data={'kind':'voice_reference'},
                         files={'file':('carry.wav',sample,'audio/wav')})
        inherited=self.client.post('/api/projects',json={'name':'下一期'}).json()
        self.assertEqual(inherited['options']['aspect_ratio'],'9:16')
        self.assertEqual(inherited['options']['resolution'],'720p')
        self.assertFalse(inherited['options']['subtitles'])
        self.assertTrue(inherited['options']['auto_edit_enabled'])
        self.assertEqual(inherited['options']['auto_edit_pause_threshold'],.45)
        self.assertIsNone(inherited['audio'])
        self.assertNotIn('script',inherited)
        self.assertEqual(inherited['script_defaults']['provider'],'indextts25')
        self.assertEqual(inherited['script_defaults']['speed'],1.1)
        self.assertTrue(core.asset_path(inherited['id'],inherited['voice_reference']).is_file())

    def setUp(self):
        self.root=Path(__file__).resolve().parent/'fixtures'/'api-checks'/uuid.uuid4().hex[:8]
        self.root.mkdir(parents=True)
        self.patch=mock.patch.object(core,'PROJECTS',self.root);self.patch.start()
        self.delete_patch=mock.patch.object(core,'DELETED_PROJECTS',self.root/'deleted-projects');self.delete_patch.start()
        self.client=TestClient(server.app)
        self.pid=self.client.post('/api/projects',json={'name':'API verification'}).json()['id']
        data=io.BytesIO()
        with wave.open(data,'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*16000*3)
        r=self.client.post(f'/api/projects/{self.pid}/upload',data={'kind':'audio'},files={'file':('test.wav',data.getvalue(),'audio/wav')})
        self.assertEqual(r.status_code,200,r.text)

    def tearDown(self):
        core.ACTIVE.pop(self.pid,None); self.client.close();self.delete_patch.stop();self.patch.stop()

    def test_delete_project_moves_everything_to_recoverable_folder(self):
        folder=core.project_dir(self.pid);marker=folder/'assets'/'keep-me.txt';marker.write_text('project asset',encoding='utf-8')
        response=self.client.delete(f'/api/projects/{self.pid}')
        self.assertEqual(response.status_code,200,response.text)
        result=response.json();self.assertTrue(result['deleted']);self.assertTrue(result['recoverable'])
        self.assertFalse(folder.exists())
        recovered=core.DELETED_PROJECTS/result['recovery_folder']
        self.assertTrue((recovered/'project.json').is_file());self.assertEqual((recovered/'assets'/'keep-me.txt').read_text(encoding='utf-8'),'project asset')
        self.assertNotIn(self.pid,{item['id'] for item in self.client.get('/api/projects').json()})
        self.assertEqual(self.client.get(f'/api/projects/{self.pid}').status_code,400)

    def test_running_project_cannot_be_deleted(self):
        core.ACTIVE[self.pid]={'cancel':False}
        response=self.client.delete(f'/api/projects/{self.pid}')
        self.assertEqual(response.status_code,400)
        self.assertTrue(core.project_dir(self.pid).is_dir())

    def test_shared_boundary_rejects_corruption(self):
        p=core.read_project(self.pid)
        p['shots']=[{'id':'a','start':0,'end':1,'kind':'A','title':'a','reason':'','keywords':[],'media_start':0},
                    {'id':'b','start':1,'end':3,'kind':'B','title':'b','reason':'','keywords':[],'media_start':0}]
        core.save_project(p)
        url=f'/api/projects/{self.pid}/shots/a'
        r=self.client.patch(url,json={'end':1.75});self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['shots'][1]['start'],1.75)
        r=self.client.patch(url,json={'end':3.5});self.assertEqual(r.status_code,400)
        self.assertEqual(core.read_project(self.pid)['shots'][0]['end'],1.75)
        core.ACTIVE[self.pid]={'cancel':False}
        self.assertEqual(self.client.patch(url,json={'end':2}).status_code,400)

    def test_shots_can_split_and_merge_on_semantic_boundaries(self):
        p=core.read_project(self.pid)
        p['candidate_segments']=[{'id':0,'start':0,'end':1.4,'text':'前半句。'},
                                 {'id':1,'start':1.5,'end':3,'text':'后半句。'}]
        p['narrative_segments']=[]
        p['shots']=[{'id':'b1','kind':'B','start':0,'end':3,'title':'完整镜头','text':'前半句。后半句。',
                     'reason':'','keywords':['完整镜头'],'media_start':0,'asset':None,'source':None,'candidates':[]}]
        core.save_project(p)
        split=self.client.post(f'/api/projects/{self.pid}/shots/b1/split',json={'time':1.4})
        self.assertEqual(split.status_code,200,split.text)
        self.assertEqual(split.json()['split_time'],1.5)
        split_id=split.json()['selected_id']
        self.assertEqual(len(core.read_project(self.pid)['shots']),2)
        merged=self.client.post(f'/api/projects/{self.pid}/shots/{split_id}/merge',json={'direction':'previous'})
        self.assertEqual(merged.status_code,200,merged.text)
        saved=core.read_project(self.pid)
        self.assertEqual(len(saved['shots']),1)
        self.assertEqual((saved['shots'][0]['start'],saved['shots'][0]['end']),(0,3))

    def test_srt_import_and_media_ranges(self):
        r=self.client.post(f'/api/projects/{self.pid}/upload',data={'kind':'srt'},files={'file':('test.srt','1\n00:00:00,000 --> 00:00:02,000\n测试字幕\n'.encode(),'text/plain')})
        self.assertEqual(r.status_code,200);self.assertEqual(len(r.json()['segments']),1)
        p=core.read_project(self.pid)
        r=self.client.get(f'/api/projects/{self.pid}/files/'+p['audio'],headers={'Range':'bytes=0-99'})
        self.assertEqual(r.status_code,206);self.assertEqual(len(r.content),100)
        self.assertEqual(self.client.get(f'/api/projects/{self.pid}/files/project.json').status_code,404)
        self.assertEqual(self.client.post('/api/projects',json={'name':'bad'},headers={'Origin':'https://external.example'}).status_code,403)

    def test_invalid_project_does_not_hold_execution_slot(self):
        before=dict(core.ACTIVE)
        with self.assertRaises(ValueError):
            with server.operation('invalid','test'):pass
        self.assertEqual(core.ACTIVE,before)
