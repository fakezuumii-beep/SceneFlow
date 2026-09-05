import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import atomic_files
import core
import server


class AtomicFileTests(unittest.TestCase):
    def test_temporary_replace_lock_preserves_old_file_until_success(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'project.json'
            target.write_text('{"revision": 1}',encoding='utf-8')
            real_replace=os.replace
            attempts=[]
            def replace(source,destination):
                attempts.append(source)
                self.assertEqual(json.loads(target.read_text())['revision'],1)
                if len(attempts)<4:raise PermissionError('locked')
                return real_replace(source,destination)
            with patch.object(atomic_files.os,'replace',side_effect=replace):
                atomic_files.atomic_json(target,{'revision':2})
            self.assertEqual(json.loads(target.read_text())['revision'],2)
            self.assertEqual(list(Path(folder).glob('*.tmp')),[])

    def test_persistent_lock_raises_and_keeps_old_and_unsaved_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'project.json'
            target.write_text('{"revision": 1}',encoding='utf-8')
            with patch.object(atomic_files.os,'replace',side_effect=PermissionError('locked')) as replace, \
                 patch.object(atomic_files.time,'sleep'):
                with self.assertRaisesRegex(RuntimeError,'待保存副本已保留'):
                    core.atomic_json(target,{'revision':2})
            self.assertEqual(replace.call_count,atomic_files.REPLACE_ATTEMPTS)
            self.assertEqual(json.loads(target.read_text())['revision'],1)
            snapshots=list(Path(folder).glob('project.json.*.tmp'))
            self.assertEqual(len(snapshots),1)
            self.assertEqual(json.loads(snapshots[0].read_text())['revision'],2)

    def test_concurrent_saves_do_not_share_temporary_names(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'project.json';barrier=threading.Barrier(2)
            real_replace=os.replace;seen=[]
            def replace(source,destination):
                seen.append(source);barrier.wait(timeout=5)
                return real_replace(source,destination)
            with patch.object(atomic_files.os,'replace',side_effect=replace):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures=[pool.submit(atomic_files.atomic_json,target,{'revision':i,'text':str(i)*4096}) for i in (1,2)]
                    for future in futures:future.result(timeout=10)
            self.assertEqual(len(set(seen)),2)
            saved=json.loads(target.read_text())
            self.assertEqual(saved['text'],str(saved['revision'])*4096)

    @unittest.skipUnless(os.name=='nt','Windows reader lock')
    def test_real_windows_project_save_recovers_after_reader_closes(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'PROJECTS',Path(folder)):
            project=core.create_project('before');target=core.project_dir(project['id'])/'project.json'
            reader=target.open('rb');timer=threading.Timer(.2,reader.close);timer.start()
            try:
                project['name']='after';core.save_project(project)
                self.assertEqual(core.read_project(project['id'])['name'],'after')
            finally:
                timer.join();reader.close()

    def test_failed_initial_save_does_not_leave_execution_slot_reserved(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'PROJECTS',Path(folder)):
            project=core.create_project('save error');project['script']={'text':'test'};core.save_project(project)
            before=dict(core.ACTIVE)
            with patch.object(core,'save_project',side_effect=RuntimeError('locked')),patch.object(core.threading,'Thread') as thread:
                with self.assertRaisesRegex(RuntimeError,'locked'):core.start_job(project['id'],'tts')
                thread.assert_not_called()
                with self.assertRaisesRegex(RuntimeError,'locked'):
                    with server.operation(project['id'],'test'):self.fail('must not run')
            self.assertEqual(core.ACTIVE,before)
