import json,sys,tempfile,uuid,wave
from pathlib import Path
from unittest import TestCase,mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import core,aroll

class ArollTests(TestCase):
    def test_video_chunks_continue_across_loop_and_chunk_boundaries(self):
        import subprocess
        root=Path(__file__).resolve().parent/'fixtures'/'aroll-checks'/uuid.uuid4().hex[:8];root.mkdir(parents=True)
        source=root/'source.mp4'
        core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','nullsrc=s=64x64:r=25,geq=lum=N*20:cb=128:cr=128',
                  '-frames:v','10','-c:v','libx264','-crf','0',source])
        first=root/'first.mp4';second=root/'second.mp4'
        aroll.prepare_video_chunk(source,first,.32,.4)
        aroll.prepare_video_chunk(source,second,.52,.2)
        def levels(path):
            raw=subprocess.check_output([str(core.FFMPEG),'-v','error','-i',str(path),'-f','rawvideo','-pix_fmt','gray','-'])
            return [sum(raw[i:i+4096])/4096 for i in range(0,len(raw),4096)]
        a,b=levels(first),levels(second)
        self.assertEqual(len(a),12);self.assertEqual(len(b),7)
        self.assertGreater(a[1],a[2]+100)  # forward wrap, without reverse or frozen frames
        for x,y in zip(a[5:],b):self.assertLess(abs(x-y),3)

    def test_installation_status_is_standalone(self):
        with tempfile.TemporaryDirectory() as folder:
            env=Path(folder);runtime=env/'Scripts/python.exe';runtime.parent.mkdir();runtime.write_bytes(b'python')
            (env/'ready.json').write_text('{}')
            with mock.patch.object(aroll,'required_files',return_value=[]),mock.patch.object(aroll,'media_python',return_value=runtime):
                status=aroll.installation_status(True)
        self.assertTrue(status['installed'])
        self.assertEqual(status['runtime'],'standalone')
        self.assertFalse(status['comfyui'])

    def test_short_tail_extends_before_trimming_and_rejects_empty_cache(self):
        root=Path(__file__).resolve().parent/'fixtures'/'aroll-checks'/uuid.uuid4().hex[:8];root.mkdir(parents=True)
        raw=root/'raw.mp4';target=root/'tail.mp4'
        core.run([core.FFMPEG,'-y','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=25:d=0.2','-c:v','libx264',raw])
        target.write_bytes(b'broken')
        self.assertFalse(aroll.valid_chunk(target,3))
        aroll.trim_chunk(raw,target,.2,3)
        self.assertTrue(aroll.valid_chunk(target,3))

    def test_signature_invalidates_only_relevant_inputs(self):
        root=Path(__file__).resolve().parent/'fixtures'/'aroll-checks'/uuid.uuid4().hex[:8];root.mkdir(parents=True)
        with mock.patch.object(core,'PROJECTS',root):
            p=core.create_project('口型签名验证');folder=core.project_dir(p['id'])
            audio=folder/'assets/audio.wav'
            with wave.open(str(audio),'wb') as f:
                f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*16000)
            p.update(audio='assets/audio.wav',duration=1)
            s={'id':'a','start':0,'end':1,'kind':'A','title':'标题'}
            signature=aroll.signature(p,s)
            s['title']='只改标题';self.assertEqual(signature,aroll.signature(p,s))
            s['end']=.8;self.assertNotEqual(signature,aroll.signature(p,s));s['end']=1
            s['aroll_signature']=signature;s['aroll_asset']='assets/finished.mp4'
            self.assertFalse(aroll.is_ready(p,s))
            (folder/s['aroll_asset']).write_bytes(b'verified elsewhere');self.assertTrue(aroll.is_ready(p,s))
            p['portrait']='assets/new.jpg';(folder/p['portrait']).write_bytes(b'a different immutable uploaded image')
            self.assertFalse(aroll.is_ready(p,s))

    def test_adjacent_aroll_shares_one_generation_run(self):
        shots=[{'id':'a1','kind':'A','start':0,'end':3.7},
               {'id':'b1','kind':'B','start':3.7,'end':7.1},
               {'id':'a2','kind':'A','start':7.1,'end':10.8},
               {'id':'a3','kind':'A','start':10.8,'end':16.284}]
        runs=aroll.contiguous_runs(shots)
        self.assertEqual([[s['id'] for s in run] for run in runs],[['a1'],['a2','a3']])

    def test_continuous_run_frame_windows_touch_without_gap_or_overlap(self):
        context_start=14.52
        a05_start=round((14.72-context_start)*aroll.FPS);cut=round((18.42-context_start)*aroll.FPS)
        a06_start=round((18.42-context_start)*aroll.FPS);end=round((23.904-context_start)*aroll.FPS)
        self.assertEqual(cut,a06_start)
        self.assertEqual((cut-a05_start)+(end-a06_start),end-a05_start)

    def test_shot_frame_counts_use_full_duration(self):
        for duration in (2.56,7.1,9.97):self.assertEqual(round(duration*aroll.FPS),round(duration*25))

    def test_batch_size_follows_settings_and_falls_back(self):
        with mock.patch.object(core,'settings',return_value={'aroll_batch_size':2}):
            self.assertEqual(aroll.batch_size(),2)
        with mock.patch.object(core,'settings',return_value={'aroll_batch_size':99}), \
             mock.patch.object(core,'settings',return_value={'aroll_batch_size':99}):
            self.assertEqual(aroll.batch_size(),8)
        self.assertIn(core._aroll_batch_size({}), (1,2,4,8,16))

    def test_oom_halves_batch_before_retry(self):
        tasks=[{'batch_size':8}]
        calls=[]
        def fake(pid,request,progress_file):
            calls.append(request['tasks'][0]['batch_size'])
            return 'torch.cuda.OutOfMemoryError: CUDA out of memory' if len(calls)==1 else None
        with mock.patch.object(aroll,'_run_worker_once',side_effect=fake),mock.patch.object(core,'progress'):
            aroll.run_worker('x',{'tasks':tasks},Path('progress.json'))
        self.assertEqual(calls,[8,4])

    def test_non_oom_failure_is_not_retried(self):
        with mock.patch.object(aroll,'_run_worker_once',return_value='RuntimeError: 模型文件损坏'):
            with self.assertRaises(RuntimeError):
                aroll.run_worker('x',{'tasks':[{'batch_size':8}]},Path('progress.json'))

    def test_interrupted_playable_cache_is_not_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            raw=Path(folder)/'raw.mp4';raw.write_bytes(b'probe mocked')
            with mock.patch.object(core,'probe',return_value={'duration':2.56,'streams':[{'codec_type':'video'}]}):
                self.assertFalse(aroll.valid_video(raw,5.0))
                self.assertTrue(aroll.valid_video(raw,2.60))
