import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import core
import wav2lip_setup as setup
from providers.aroll import get_aroll_provider
from providers.aroll import wav2lip as provider_module


class _Response:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, _):
        yield self.body


class Wav2LipSetupTests(unittest.TestCase):
    def test_progress_output_survives_a_non_utf8_console(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding='ascii')
        with patch.object(setup.sys, 'stdout', stream):
            setup.emit(42, '校验模型')
            stream.flush()
        self.assertIn(b'\\u6821\\u9a8c\\u6a21\\u578b', raw.getvalue())

    def test_app_code_without_runtime_is_not_an_installed_engine(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(setup, 'ENGINES', Path(folder)):
            status = setup.installation_status()
        self.assertFalse(status['ready'])
        self.assertFalse(status['installed'])
        self.assertIn('尚未安装', status['message'])

    def test_cli_installer_requires_explicit_license_acknowledgement(self):
        with patch('sys.argv', ['wav2lip_setup.py']):
            with self.assertRaisesRegex(RuntimeError, '必须先阅读并确认'):
                setup.main()

    def test_resumable_download_appends_verified_range(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'model.pt'
            target.with_suffix('.pt.part').write_bytes(b'abc')
            sha = hashlib.sha256(b'abcdef').hexdigest()
            response = _Response(b'def', 206, {'Content-Range': 'bytes 3-5/6'})
            with patch.object(setup.requests, 'get', return_value=response) as request:
                setup.download('https://example.test/model', target, 6, sha)
            self.assertEqual(target.read_bytes(), b'abcdef')
            self.assertFalse(target.with_suffix('.pt.part').exists())
            self.assertEqual(request.call_args.kwargs['headers'], {'Range': 'bytes=3-'})

    def test_manual_checkpoint_with_wrong_sha_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(setup, 'ENGINES', Path(folder)), \
             patch.object(setup, 'CHECKPOINT_SIZE', 3), \
             patch.object(setup, 'CHECKPOINT_SHA256', hashlib.sha256(b'abc').hexdigest()):
            manual = Path(folder) / 'wrong.pt'
            manual.write_bytes(b'def')
            with self.assertRaisesRegex(RuntimeError, 'SHA256'):
                setup.install_checkpoint(manual)
            self.assertFalse(setup.checkpoint_path().exists())

    def test_ready_manifest_records_pinned_runtime_and_model(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(setup, 'ENGINES', Path(folder)), \
             patch.object(setup, 'environment_size', return_value=1234):
            setup.ready_path().parent.mkdir(parents=True)
            setup.write_ready({'python': setup.PYTHON_VERSION, 'torch': setup.TORCH_VERSION + '+cu126',
                               'cuda_runtime': '12.6', 'cuda_available': True})
            record = json.loads(setup.ready_path().read_text(encoding='utf-8'))
            self.assertEqual(record['source_revision'], setup.SOURCE_REVISION)
            self.assertEqual(record['checkpoint_sha256'], setup.CHECKPOINT_SHA256)
            self.assertEqual(record['environment_size'], 1234)
            self.assertEqual(record['device'], 'cuda')

    def test_status_detects_complete_and_damaged_installations(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(setup, 'ENGINES', Path(folder)), \
             patch.object(setup, 'CHECKPOINT_SIZE', 3), patch.object(setup, 'S3FD_SIZE', 4):
            for path, data in (
                (setup.runtime_python(), b'python'),
                (setup.source_root() / 'models/wav2lip.py', b'code'),
                (setup.source_root() / 'face_detection/detection/sfd/net_s3fd.py', b'code'),
                (setup.checkpoint_path(), b'abc'),
                (setup.detector_path(), b'defg'),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            marker = setup.source_root() / 'workbench-source.json'
            marker.write_text(json.dumps({'repo': setup.SOURCE_REPO,
                                          'revision': setup.SOURCE_REVISION,
                                          'archive_sha256': setup.SOURCE_ARCHIVE_SHA256}), encoding='utf-8')
            setup.ready_path().write_text(json.dumps({
                'provider_version': setup.PROVIDER_VERSION,
                'adapter_version': setup.ADAPTER_VERSION,
                'license_reference': setup.LICENSE_REFERENCE,
                'repo': setup.SOURCE_REPO,
                'source_revision': setup.SOURCE_REVISION,
                'checkpoint': setup.CHECKPOINT_NAME,
                'checkpoint_size': 3,
                'checkpoint_sha256': setup.CHECKPOINT_SHA256,
                's3fd': setup.S3FD_NAME,
                's3fd_size': 4,
                's3fd_sha256': setup.S3FD_SHA256,
                'python': setup.PYTHON_VERSION,
                'torch': setup.TORCH_VERSION + '+cu126',
                'device': 'cuda',
            }), encoding='utf-8')
            self.assertTrue(setup.installation_status()['ready'])
            (setup.source_root() / 'models/wav2lip.py').unlink()
            damaged = setup.installation_status()
            self.assertFalse(damaged['ready'])
            self.assertTrue(damaged['installed'])


class Wav2LipProviderTests(unittest.TestCase):
    def settings(self):
        return {'aroll_provider': 'wav2lip', 'wav2lip_license_acknowledged': True,
                'wav2lip_license_reference': setup.LICENSE_REFERENCE}

    def test_unacknowledged_provider_stays_not_ready(self):
        provider = get_aroll_provider({'aroll_provider': 'wav2lip'})
        with patch.object(setup, 'installation_status', return_value={
                'ready': True, 'installed': True, 'message': 'ready'}):
            status = provider.status()
        self.assertFalse(status['ready'])
        self.assertFalse(status['license_acknowledged'])

    def test_generate_delegates_to_isolated_worker_facade(self):
        provider = get_aroll_provider(self.settings())
        with patch.object(setup, 'installation_status', return_value={
                'ready': True, 'installed': True, 'message': 'ready'}), \
             patch.object(provider_module, 'generate', return_value='done') as generate:
            self.assertEqual(provider.generate('project', 'shot'), 'done')
        identity = generate.call_args.args[2]
        self.assertEqual(identity['provider'], 'wav2lip')
        self.assertEqual(identity['checkpoint'], setup.CHECKPOINT_SHA256)

    def test_oom_retries_with_half_batch(self):
        request = {'tasks': [{'batch_size': 8}]}
        with patch.object(provider_module, '_run_worker_once',
                          side_effect=['CUDA out of memory', None]) as worker, \
             patch.object(core, 'progress'):
            provider_module.run_worker('project', request, Path('progress.json'))
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(request['tasks'][0]['batch_size'], 4)

    def test_worker_has_one_entrypoint(self):
        source = (Path(__file__).resolve().parents[1] / 'wav2lip_worker.py').read_text(encoding='utf-8')
        self.assertEqual(source.count("if __name__ == '__main__':"), 1)


if __name__ == '__main__':
    unittest.main()
