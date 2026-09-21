import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import core
from providers import public_catalog
from providers.llm import resolve_llm_config
from providers.aroll import get_aroll_provider, get_project_aroll_provider


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
            core.save_settings({'llm_api_key': 'top-secret', 'pexels_api_key': 'stock-secret',
                                'aroll_autodl_api_key': 'autodl-secret-token','tts_seed_api_key':'seed-secret'})
            core.save_settings({'llm_api_key': '', 'pexels_api_key': '', 'aroll_autodl_api_key': '',
                                'tts_seed_api_key':''})
            public = core.settings()
            encoded = json.dumps(public)
            self.assertFalse(any(key.endswith('api_key') for key in public))
            self.assertNotIn('top-secret', encoded)
            self.assertNotIn('stock-secret', encoded)
            self.assertNotIn('autodl-secret-token', encoded)
            self.assertNotIn('seed-secret', encoded)
            self.assertTrue(public['llm_api_key_configured'])
            self.assertTrue(public['pexels_api_key_configured'])
            self.assertTrue(public['aroll_autodl_api_key_configured'])
            self.assertTrue(public['tts_seed_api_key_configured'])

    def test_h3_legacy_prompt_setting_is_removed(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'PRIVATE',Path(folder)):
            private=Path(folder);private.mkdir(exist_ok=True)
            (private/'settings.json').write_text(json.dumps({'aroll_autodl_prompt':'unused'}),encoding='utf-8')
            self.assertNotIn('aroll_autodl_prompt',core.settings())
            self.assertNotIn('aroll_autodl_prompt',json.loads((private/'settings.json').read_text(encoding='utf-8')))
            self.assertNotIn('aroll_autodl_prompt',core.save_settings({'aroll_autodl_prompt':'ignored'}))

    def test_infinitetalk_workflow_prompts_become_editable_global_defaults(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'PRIVATE',Path(folder)):
            private=Path(folder);workflow=private/'single.json'
            workflow.write_text(json.dumps({
                '1':{'class_type':'LoadImage','inputs':{'image':'host.png'}},
                '2':{'class_type':'LoadAudio','inputs':{'audio':'voice.wav'}},
                '3':{'class_type':'MultiTalkWav2VecEmbeds','inputs':{'audio_1':['2',0],'num_frames':100,'fps':25}},
                '4':{'class_type':'VHS_VideoCombine','inputs':{'frame_rate':25}},
                '5':{'class_type':'WanVideoTextEncodeCached','inputs':{
                    'positive_prompt':'workflow positive','negative_prompt':'workflow negative'}},
            }),encoding='utf-8')
            configured={
                'aroll_provider':'infinitetalk','aroll_comfyui_url':'http://127.0.0.1:8188',
                'aroll_comfyui_workflow':'single.json','aroll_comfyui_workflow_hash':'test-workflow',
                'aroll_person_node':'1',
                'aroll_audio_node':'2','aroll_output_node':'4',
            }
            public=core.save_settings(configured)
            self.assertTrue(public['aroll_infinitetalk_prompt_supported'])
            self.assertEqual(public['aroll_infinitetalk_positive_prompt'],'workflow positive')
            self.assertEqual(public['aroll_infinitetalk_negative_prompt'],'workflow negative')
            public=core.save_settings({'aroll_infinitetalk_positive_prompt':'custom positive',
                                       'aroll_infinitetalk_negative_prompt':'custom negative'})
            self.assertEqual(public['aroll_infinitetalk_positive_prompt'],'custom positive')
            self.assertEqual(public['aroll_infinitetalk_negative_prompt'],'custom negative')
            with self.assertRaisesRegex(ValueError,'4000'):
                core.save_settings({'aroll_infinitetalk_positive_prompt':'x'*4001})

    def test_all_aroll_provider_selections_resolve(self):
        cases = [
            ({'aroll_provider': 'latentsync'}, 'latentsync'),
            ({'aroll_provider': 'wav2lip'}, 'wav2lip'),
            ({'aroll_provider': 'musetalk'}, 'musetalk'),
            ({'aroll_provider': 'infinitetalk'}, 'infinitetalk'),
            ({'aroll_provider': 'autodl_h3'}, 'autodl_h3'),
            ({'aroll_provider': 'custom', 'aroll_custom_type': 'comfyui'}, 'comfyui'),
            ({'aroll_provider': 'custom', 'aroll_custom_type': 'external_api'}, 'external_api'),
        ]
        for settings, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(get_aroll_provider(settings).id, expected)

    def test_project_provider_overrides_shared_default_without_copying_credentials(self):
        settings={'aroll_provider':'infinitetalk','aroll_autodl_api_key':'secret-token'}
        project={'aroll_provider_id':'autodl_h3'}
        provider=get_project_aroll_provider(settings,project)
        self.assertEqual(provider.id,'autodl_h3')
        self.assertEqual(provider.settings['aroll_autodl_api_key'],'secret-token')
        self.assertNotIn('aroll_autodl_api_key',project)

    def test_legacy_project_provider_is_inferred_from_existing_aroll_provenance(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'PROJECTS',Path(folder)):
            project=core.create_project('legacy h3')
            project['aroll_provider_id']='infinitetalk'
            project.pop('aroll_provider_scope_version',None)
            project['shots']=[{'id':'a','kind':'A','start':0,'end':1,
                               'aroll_provenance':{'provider':'autodl_h3'}}]
            core.save_project(project)
            migrated=core.read_project(project['id'])
            self.assertEqual(migrated['aroll_provider_id'],'autodl_h3')
            self.assertEqual(migrated['aroll_provider_scope_version'],1)

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
            latent = get_aroll_provider({'aroll_provider': 'latentsync',
                                         'aroll_latentsync_url': 'http://127.0.0.1:8189'})
            wave_provider = get_aroll_provider({'aroll_provider': 'wav2lip'})
            self.assertNotEqual(muse.signature(project, shot), latent.signature(project, shot))
            self.assertNotEqual(muse.signature(project, shot), wave_provider.signature(project, shot))
            first = get_aroll_provider({'aroll_provider': 'custom', 'aroll_custom_type': 'comfyui',
                                        'aroll_comfyui_workflow_hash': 'workflow-a'})
            second = get_aroll_provider({'aroll_provider': 'custom', 'aroll_custom_type': 'comfyui',
                                         'aroll_comfyui_workflow_hash': 'workflow-b'})
            self.assertNotEqual(first.signature(project, shot), second.signature(project, shot))

    def test_musetalk_quality_parameters_change_cache_identity(self):
        highest=get_aroll_provider({'aroll_provider':'musetalk','aroll_musetalk_quality':'highest',
                                    'aroll_musetalk_parsing_mode':'jaw','aroll_musetalk_extra_margin':10,
                                    'aroll_musetalk_left_cheek_width':90,'aroll_musetalk_right_cheek_width':90,
                                    'aroll_musetalk_audio_padding_left':2,'aroll_musetalk_audio_padding_right':2})
        balanced=get_aroll_provider({'aroll_provider':'musetalk','aroll_musetalk_quality':'balanced',
                                     'aroll_musetalk_parsing_mode':'jaw','aroll_musetalk_extra_margin':10,
                                     'aroll_musetalk_left_cheek_width':90,'aroll_musetalk_right_cheek_width':90,
                                     'aroll_musetalk_audio_padding_left':2,'aroll_musetalk_audio_padding_right':2})
        self.assertEqual(highest.runtime_config()['precision'],'float32')
        self.assertEqual(highest.runtime_config()['crf'],14)
        self.assertNotEqual(highest.cache_identity(),balanced.cache_identity())

    def test_musetalk_quality_settings_are_validated(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core,'PRIVATE',Path(folder)):
            saved=core.save_settings({'aroll_musetalk_quality':'highest',
                                      'aroll_musetalk_parsing_mode':'jaw',
                                      'aroll_musetalk_extra_margin':'14',
                                      'aroll_musetalk_left_cheek_width':'90',
                                      'aroll_musetalk_right_cheek_width':'95',
                                      'aroll_musetalk_audio_padding_left':'2',
                                      'aroll_musetalk_audio_padding_right':'3'})
            self.assertEqual(saved['aroll_musetalk_extra_margin'],14)
            self.assertEqual(saved['aroll_musetalk_right_cheek_width'],95)
            with self.assertRaisesRegex(ValueError,'下巴范围'):
                core.save_settings({'aroll_musetalk_extra_margin':41})

    def test_preflight_reports_friendly_missing_provider_steps(self):
        project = {'audio': None, 'script': {'text': '你好'}, 'shots': [], 'options': {'broll_ratio': 60}}
        cfg = core._settings_defaults()
        cfg['aroll_provider'] = 'musetalk'
        with patch.object(core, 'settings', return_value=cfg), \
             patch('aroll.installation_status', return_value={'installed': False, 'message': '尚未安装'}):
            result = core.generation_preflight(project)
        self.assertFalse(result['ok'])
        self.assertEqual([item['code'] for item in result['issues']], ['llm', 'broll', 'aroll'])
        self.assertTrue(all('Traceback' not in item['message'] for item in result['issues']))


if __name__ == '__main__':
    unittest.main()
