import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import core
from providers import public_catalog
from providers.llm import resolve_llm_config
from providers.aroll import get_aroll_provider


class ProviderTests(unittest.TestCase):
    def test_deepseek_is_a_fixed_server_owned_preset(self):
        cfg = resolve_llm_config({'llm_provider': 'deepseek', 'llm_api_key': 'secret'}, require_key=True)
        self.assertEqual(cfg['base_url'], 'https://api.deepseek.com')
        self.assertEqual(cfg['model'], 'deepseek-v4-flash')
        self.assertEqual(cfg['api_key'], 'secret')
        self.assertEqual(cfg['request_options']['thinking'], {'type': 'disabled'})
        catalog = json.dumps(public_catalog(), ensure_ascii=False)
        self.assertNotIn('api.deepseek.com', catalog)
        self.assertNotIn('deepseek-v4-flash', catalog)

    def test_custom_openai_compatible_resolves_without_provider_branching_upstream(self):
        cfg = resolve_llm_config({
            'llm_provider': 'custom', 'llm_api_key': 'token', 'llm_custom_name': '内部网关',
            'llm_custom_base_url': 'https://models.example.test/v1/', 'llm_custom_model': 'story-model',
        }, require_key=True)
        self.assertEqual((cfg['provider'], cfg['name']), ('custom', '内部网关'))
        self.assertEqual((cfg['base_url'], cfg['model']), ('https://models.example.test/v1', 'story-model'))
        self.assertEqual(cfg['request_options'], {})

    def test_legacy_deepseek_settings_migrate_without_losing_keys(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'PRIVATE', Path(folder)):
            path = Path(folder) / 'settings.json'
            path.write_text(json.dumps({
                'llm_base_url': 'https://api.deepseek.com', 'llm_model': 'deepseek-v4-flash',
                'llm_api_key': 'old-llm-key', 'pexels_api_key': 'old-stock-key',
            }), encoding='utf-8')
            private = core.settings(True)
            stored = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(private['llm_provider'], 'deepseek')
            self.assertEqual(private['llm_api_key'], 'old-llm-key')
            self.assertEqual(private['pexels_api_key'], 'old-stock-key')
            self.assertNotIn('llm_base_url', stored)
            self.assertNotIn('llm_model', stored)

    def test_unrecognized_legacy_llm_migrates_to_custom(self):
        raw = {'llm_base_url': 'https://gateway.example/v1', 'llm_model': 'old-model', 'llm_api_key': 'keep'}
        migrated, changed = core._migrate_settings(raw)
        self.assertTrue(changed)
        self.assertEqual(migrated['llm_provider'], 'custom')
        self.assertEqual(migrated['llm_custom_base_url'], 'https://gateway.example/v1')
        self.assertEqual(migrated['llm_custom_model'], 'old-model')
        self.assertEqual(migrated['llm_api_key'], 'keep')

    def test_public_settings_never_return_api_keys_and_blank_save_preserves_them(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'PRIVATE', Path(folder)):
            core.save_settings({'llm_api_key': 'top-secret', 'pexels_api_key': 'stock-secret'})
            core.save_settings({'llm_api_key': '', 'pexels_api_key': ''})
            public = core.settings()
            encoded = json.dumps(public)
            self.assertFalse(any(key.endswith('api_key') for key in public))
            self.assertNotIn('top-secret', encoded)
            self.assertNotIn('stock-secret', encoded)
            self.assertTrue(public['llm_api_key_configured'])
            self.assertTrue(public['pexels_api_key_configured'])

    def test_all_aroll_provider_selections_resolve(self):
        cases = [
            ({'aroll_provider': 'wav2lip'}, 'wav2lip'),
            ({'aroll_provider': 'musetalk'}, 'musetalk'),
            ({'aroll_provider': 'custom', 'aroll_custom_type': 'comfyui'}, 'comfyui'),
            ({'aroll_provider': 'custom', 'aroll_custom_type': 'external_api'}, 'external_api'),
        ]
        for settings, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(get_aroll_provider(settings).id, expected)

    def test_provider_and_workflow_changes_invalidate_aroll_signature(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, 'PROJECTS', Path(folder)), \
             patch.object(core, 'DEFAULT_LOOP_VIDEO', Path(folder) / 'missing.mp4'):
            project = core.create_project('provider-signature')
            root = core.project_dir(project['id'])
            audio = root / 'assets' / 'audio.wav'
            with wave.open(str(audio), 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(16000)
                stream.writeframes(b'\0\0' * 16000)
            shot = {'id': 'a', 'start': 0, 'end': 1, 'kind': 'A'}
            project.update(audio='assets/audio.wav', duration=1, shots=[shot])
            muse = get_aroll_provider({'aroll_provider': 'musetalk'})
            wave_provider = get_aroll_provider({'aroll_provider': 'wav2lip'})
            self.assertNotEqual(muse.signature(project, shot), wave_provider.signature(project, shot))
            first = get_aroll_provider({'aroll_provider': 'custom', 'aroll_custom_type': 'comfyui',
                                        'aroll_comfyui_workflow_hash': 'workflow-a'})
            second = get_aroll_provider({'aroll_provider': 'custom', 'aroll_custom_type': 'comfyui',
                                         'aroll_comfyui_workflow_hash': 'workflow-b'})
            self.assertNotEqual(first.signature(project, shot), second.signature(project, shot))

    def test_preflight_reports_friendly_missing_provider_steps(self):
        project = {'audio': None, 'script': {'text': '你好'}, 'shots': [], 'options': {'broll_ratio': 60}}
        cfg = core._settings_defaults()
        with patch.object(core, 'settings', return_value=cfg), \
             patch('aroll.installation_status', return_value={'installed': False, 'message': '尚未安装'}):
            result = core.generation_preflight(project)
        self.assertFalse(result['ok'])
        self.assertEqual([item['code'] for item in result['issues']], ['llm', 'broll', 'aroll'])
        self.assertTrue(all('Traceback' not in item['message'] for item in result['issues']))


if __name__ == '__main__':
    unittest.main()
