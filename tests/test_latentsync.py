import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from providers.aroll import get_aroll_provider
from providers.aroll.latentsync import LatentSyncProvider


class LatentSyncProviderTests(unittest.TestCase):
    def provider(self):
        return get_aroll_provider({
            'aroll_provider': 'latentsync',
            'aroll_latentsync_url': 'http://127.0.0.1:8189',
            'aroll_latentsync_lips_expression': 2.2,
            'aroll_latentsync_inference_steps': 35,
        })

    def test_prompt_uses_verified_25fps_workflow_and_tuning(self):
        prompt = self.provider().build_prompt('host.mp4', 'voice.wav', 'SceneFlow/test')
        self.assertEqual(prompt['1']['class_type'], 'VHS_LoadVideo')
        self.assertEqual(prompt['1']['inputs']['force_rate'], 25)
        self.assertEqual(prompt['2']['class_type'], 'LoadAudio')
        self.assertEqual(prompt['3']['class_type'], 'LatentSyncNode')
        self.assertEqual(prompt['3']['inputs']['lips_expression'], 2.2)
        self.assertEqual(prompt['3']['inputs']['inference_steps'], 35)
        self.assertEqual(prompt['4']['inputs']['format'], 'video/h264-mp4')
        self.assertTrue(prompt['4']['inputs']['trim_to_audio'])

    def test_tuning_is_part_of_cache_identity(self):
        identity = self.provider().cache_identity()
        self.assertEqual(identity['lips_expression'], 2.2)
        self.assertEqual(identity['inference_steps'], 35)

    def test_tuning_rejects_values_outside_wrapper_range(self):
        provider = self.provider()
        provider.settings['aroll_latentsync_lips_expression'] = 3.1
        with self.assertRaisesRegex(ValueError, '1.0 到 3.0'):
            provider.validate_config()

    def test_connection_requires_latentsync_nodes(self):
        provider = self.provider()
        stats = Mock()
        stats.json.return_value = {'devices': [{'name': 'cuda:0 RTX 2080 Ti'}]}
        schema = Mock()
        schema.json.return_value = {
            'VHS_LoadVideo': {}, 'LoadAudio': {}, 'VHS_VideoCombine': {},
            'LatentSyncNode': {'input': {'required': {
                'images': {}, 'audio': {}, 'seed': {}, 'lips_expression': {}, 'inference_steps': {},
            }}},
        }
        with patch.object(provider, 'request', side_effect=[stats, schema]):
            result = provider.test_connection()
        self.assertTrue(result['ok'])
        self.assertIn('2080 Ti', result['message'])

    def test_upload_preserves_comfyui_subfolder(self):
        provider = self.provider()
        response = Mock()
        response.json.return_value = {'name': 'host.mp4', 'subfolder': 'SceneFlow', 'type': 'input'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'host.mp4'
            path.write_bytes(b'video')
            with patch.object(provider, 'request', return_value=response):
                self.assertEqual(provider.upload(path), 'SceneFlow/host.mp4')


if __name__ == '__main__':
    unittest.main()
