import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from whisper_models import resolve_local_model


class WhisperModelsTests(unittest.TestCase):
    def _snapshot(self, folder, model='base', vocabulary='vocabulary.txt'):
        snapshot = Path(folder) / f'models--Systran--faster-whisper-{model}' / 'snapshots' / 'revision'
        snapshot.mkdir(parents=True)
        for name in ('model.bin', 'config.json', 'tokenizer.json', vocabulary):
            (snapshot / name).write_bytes(b'data')
        return snapshot

    def test_shared_cache_snapshot_is_used_without_ref(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = self._snapshot(folder)
            with patch.dict(os.environ, {'HF_HUB_CACHE': folder}):
                self.assertEqual(resolve_local_model(Path(folder) / 'app', 'base'), snapshot.resolve())
                (snapshot / 'tokenizer.json').unlink()
                self.assertIsNone(resolve_local_model(Path(folder) / 'app', 'base'))

    def test_large_v3_json_vocabulary_is_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = self._snapshot(folder, 'large-v3', 'vocabulary.json')
            with patch.dict(os.environ, {'HF_HUB_CACHE': folder}):
                self.assertEqual(resolve_local_model(Path(folder) / 'app', 'large-v3'), snapshot.resolve())

    def test_hf_home_is_respected_without_home_lookup(self):
        with tempfile.TemporaryDirectory() as folder:
            snapshot = self._snapshot(Path(folder) / 'hub')
            with patch.dict(os.environ, {'HF_HOME': folder}, clear=True):
                self.assertEqual(resolve_local_model(Path(folder) / 'app', 'base'), snapshot.resolve())
