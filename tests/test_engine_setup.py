import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import engine_setup


class EngineSetupTests(unittest.TestCase):
    def test_model_download_filters_to_only_requested_files(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {'siblings': [
            {'rfilename': 'wanted.bin', 'size': 3},
            {'rfilename': 'not-requested.bin', 'size': 4},
        ]}

        def fake_download(url, target, sha=None, size=None):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'abc')

        with tempfile.TemporaryDirectory() as folder, \
             patch('engine_setup.requests.get', return_value=response), \
             patch('engine_setup.download', side_effect=fake_download) as download:
            root = Path(folder) / 'model'
            engine_setup.model('owner/repo', 'revision', root, ['wanted.bin'])
            self.assertTrue((root / 'wanted.bin').is_file())
            self.assertFalse((root / 'not-requested.bin').exists())
            self.assertEqual(download.call_count, 1)
            self.assertEqual(download.call_args.args[1], root / 'wanted.bin')


if __name__ == '__main__':
    unittest.main()
