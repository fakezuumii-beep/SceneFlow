import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import worker_progress


class WorkerProgressTests(unittest.TestCase):
    def test_transient_lock_retries_without_truncating_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'progress.json'
            target.write_text('{"batch": 1}', encoding='utf-8')
            replace = os.replace
            attempts = []
            def locked_then_released(source, destination):
                attempts.append(source)
                if len(attempts) < 3:
                    self.assertEqual(json.loads(target.read_text())['batch'], 1)
                    raise PermissionError('reader holds destination')
                replace(source, destination)
            with patch.object(worker_progress.os, 'replace', side_effect=locked_then_released):
                self.assertTrue(worker_progress.atomic_json(target, {'batch': 2}))
            self.assertEqual(json.loads(target.read_text())['batch'], 2)
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_persistent_lock_skips_snapshot_and_next_update_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'progress.json'
            worker_progress.atomic_json(target, {'batch': 1})
            with patch.object(worker_progress.os, 'replace', side_effect=PermissionError('locked')):
                self.assertFalse(worker_progress.atomic_json(target, {'batch': 2}))
            self.assertEqual(json.loads(target.read_text())['batch'], 1)
            self.assertTrue(worker_progress.atomic_json(target, {'batch': 3}))
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_real_windows_reader_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'progress.json'
            worker_progress.atomic_json(target, {'batch': 1})
            reader = target.open('rb')
            timer = threading.Timer(.08, reader.close)
            timer.start()
            try:
                self.assertTrue(worker_progress.atomic_json(target, {'batch': 2}))
                self.assertEqual(json.loads(target.read_text())['batch'], 2)
            finally:
                timer.join()
                reader.close()
