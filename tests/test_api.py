import copy, io, json, sys, uuid, wave
from pathlib import Path
from unittest import TestCase, mock
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core, server

class ApiTests(TestCase):
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
        result=self.client.get('/api/local-models').json()
        self.assertEqual(result['tts']['provider'],'azure-v1')
        self.assertEqual(result['tts']['name'],'Azure TTS V1')
        self.assertIn('zh-CN-XiaoxiaoNeural',result['azure_voices']['Chinese'])

    def setUp(self):
        self.root=Path(__file__).resolve().parent/'fixtures'/'api-checks'/uuid.uuid4().hex[:8]
        self.root.mkdir(parents=True)
        self.patch=mock.patch.object(core,'PROJECTS',self.root);self.patch.start()
        self.client=TestClient(server.app)
        self.pid=self.client.post('/api/projects',json={'name':'API verification'}).json()['id']
        data=io.BytesIO()
        with wave.open(data,'wb') as f:
            f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*16000*3)
        r=self.client.post(f'/api/projects/{self.pid}/upload',data={'kind':'audio'},files={'file':('test.wav',data.getvalue(),'audio/wav')})
        self.assertEqual(r.status_code,200,r.text)

    def tearDown(self):
        core.ACTIVE.pop(self.pid,None); self.client.close();self.patch.stop()

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
