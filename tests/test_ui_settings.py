import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UiSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')
        cls.javascript = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
        cls.css = (ROOT / 'static' / 'style.css').read_text(encoding='utf-8')

    def test_header_opens_global_api_settings(self):
        header = re.search(r'<header>.*?</header>', self.html, re.S).group(0)
        self.assertIn('id="globalApiButton"', header)
        self.assertIn('连接与设置', header)
        self.assertNotIn('id="exportButton"', header)
        self.assertIn("$('#globalApiButton').onclick=()=>guarded(openGlobalApiSettings)", self.javascript)

    def test_global_dialog_contains_provider_settings(self):
        dialog = re.search(r'<dialog id="settingsDialog".*?</dialog>', self.html, re.S).group(0)
        for name in ('llm_provider', 'llm_api_key', 'llm_custom_base_url', 'llm_custom_model',
                     'broll_provider', 'pexels_api_key', 'pixabay_api_key', 'aroll_provider',
                     'aroll_custom_type', 'aroll_comfyui_workflow_hash', 'aroll_external_api_key'):
            self.assertIn(f'name="{name}"', dialog)
        self.assertIn('所有项目共用这些服务', dialog)
        self.assertIn('完整密钥只保存在本机', dialog)
        self.assertIn('<details class="settings-advanced">', dialog)
        self.assertIn('data-test-provider="llm"', dialog)
        self.assertIn('data-test-provider="broll"', dialog)
        self.assertIn('data-test-provider="aroll"', dialog)
        self.assertIn('rel="noopener noreferrer"', dialog)
        self.assertIn("placeholder=s[key+'_configured']?'••••••••••••':'尚未配置'", self.javascript)

    def test_simple_provider_modes_hide_technical_fields_by_default(self):
        dialog = re.search(r'<dialog id="settingsDialog".*?</dialog>', self.html, re.S).group(0)
        self.assertNotIn('https://api.deepseek.com', dialog)
        self.assertNotIn('deepseek-v4-flash', dialog)
        self.assertIn('id="llmCustomFields" class="hidden"', dialog)
        self.assertIn('id="customArollFields" class="aroll-mode hidden"', dialog)
        self.assertIn("$('#llmCustomFields').classList.toggle('hidden',llm!=='custom')", self.javascript)
        self.assertIn("$('#customArollFields').classList.toggle('hidden',aroll!=='custom')", self.javascript)

    def test_home_aroll_badge_is_provider_driven(self):
        self.assertIn('id="arollBadge">人物口型</span>', self.html)
        self.assertNotIn('id="arollBadge">MuseTalk', self.html)
        self.assertIn("$('#arollBadge').textContent=status.aroll.short_name||status.aroll.name", self.javascript)

    def test_export_action_remains_in_production_settings(self):
        header_end = self.html.index('</header>')
        export_position = self.html.index('id="exportButton"')
        settings_panel = self.html.index('id="setupPanel"')
        self.assertGreater(export_position, header_end)
        self.assertGreater(export_position, settings_panel)
        self.assertIn("$('#exportButton').onclick=()=>startJob('render')", self.javascript)

    def test_beginner_panel_only_keeps_episode_level_choices(self):
        panel = self.html.split('<section id="setupPanel"', 1)[1].split('</section>', 1)[0]
        self.assertIn('画面风格', panel)
        self.assertIn('id="subtitlesToggle"', panel)
        self.assertIn('id="resolution"', panel)
        self.assertIn('高级制作设置', panel)
        self.assertIn('id="planButton"', panel)
        self.assertIn('id="materialsButton"', panel)
        self.assertNotIn('id="asrModel"', panel)
        self.assertNotIn('Whisper', panel)
        self.assertNotIn('MuseTalk', panel)
        self.assertNotIn('Pexels', panel)

    def test_whisper_models_are_global_advanced_settings(self):
        dialog = re.search(r'<dialog id="settingsDialog".*?</dialog>', self.html, re.S).group(0)
        self.assertIn('name="asr_model"', dialog)
        for model in ('large-v3', 'small', 'base'):
            self.assertIn(f'value="{model}"', dialog)
        self.assertIn('applyAsrSettings(state.settingsData)', self.javascript)

    def test_preflight_dialog_routes_missing_configuration(self):
        dialog = self.html.split('<dialog id="preflightDialog">', 1)[1].split('</dialog>', 1)[0]
        self.assertIn('开始生成前还差一步', dialog)
        self.assertIn('id="preflightInstall"', dialog)
        self.assertIn('id="preflightSettings"', dialog)
        self.assertIn("api('/projects/'+pid()+'/preflight')", self.javascript)

    def test_installer_supports_project_local_offline_runtime(self):
        installer=(ROOT/'安装工作台.ps1').read_text(encoding='utf-8')
        engine=(ROOT/'engine_setup.py').read_text(encoding='utf-8')
        self.assertIn('UV_PYTHON_INSTALL_DIR',installer)
        self.assertIn(".offline\\main-wheels",installer)
        self.assertIn("OFFLINE/'media-wheels'",engine)
        self.assertIn("torch==2.8.0+cu126",engine)

    def test_running_pipeline_uses_the_eight_character_frames(self):
        self.assertIn('function runningPipelineStage(p)', self.javascript)
        self.assertIn("const direct={tts:0,transcribe:0,plan:1,materials:2,aroll:2,render:3}", self.javascript)
        self.assertIn('class="pipeline-worker"', self.javascript)
        self.assertIn('/pipeline-animations/step${i+1}-frame1.png', self.javascript)
        self.assertIn('/pipeline-animations/step${i+1}-frame2.png', self.javascript)
        for step in range(1, 5):
            for frame in range(1, 3):
                image = ROOT / 'static' / 'pipeline-animations' / f'step{step}-frame{frame}.png'
                self.assertTrue(image.is_file(), image)
                self.assertGreater(image.stat().st_size, 100_000)

    def test_quick_launch_art_follows_readiness_and_ready_border_shines(self):
        not_ready = ROOT / 'static' / 'quick-launch-backgrounds' / 'not-ready.png'
        ready = ROOT / 'static' / 'quick-launch-backgrounds' / 'ready.png'
        self.assertTrue(not_ready.is_file())
        self.assertTrue(ready.is_file())
        self.assertGreater(not_ready.stat().st_size, 1_000_000)
        self.assertGreater(ready.stat().st_size, 1_000_000)
        self.assertIn("url('/quick-launch-backgrounds/ready.png')", self.css)
        self.assertIn("url('/quick-launch-backgrounds/not-ready.png')", self.css)
        self.assertIn('.quick-launch:not(.pending)::after', self.css)
        self.assertIn('animation:quick-launch-border-sweep', self.css)
        self.assertIn('/style.css?v=20260908-provider-ui-v1', self.html)
        self.assertIn('.quick-launch>#quickLaunchStatus{display:none}', self.css)
        self.assertIn('filter:none', self.css)
        self.assertIn("background:url('/quick-launch-backgrounds/ready.png')", self.css)
        self.assertIn("linear-gradient(145deg,#758078a8,#aab09a8f),url('/quick-launch-backgrounds/not-ready.png')", self.css)
        self.assertIn('background-blend-mode:color', self.css)
        self.assertIn('drop-shadow(0 0 5px #83d9cb)', self.css)
        self.assertIn('filter:none', self.css)
        self.assertIn('.quick-launch #autoButton{opacity:1', self.css)

    def test_quick_launch_keeps_ready_art_and_updates_button_during_generation(self):
        self.assertIn("const sourceReady=!!(p.audio||$('#scriptText').value.trim()),activeIssues=", self.javascript)
        self.assertIn('launchReady=sourceReady&&state.arollSupported&&providersReady', self.javascript)
        self.assertNotIn('launchReady=sourceReady&&!state.busy&&state.arollSupported', self.javascript)
        self.assertIn("const oneClickGenerating=state.startingAction==='all'||(j?.status==='running'&&j.action==='all')", self.javascript)
        self.assertIn("oneClickGenerating?'正在生成':currentVersionExported?'重新生成':'一键生成播客'", self.javascript)
        self.assertIn("const currentVersionExported=p.exports.some(e=>e.revision===p.revision)", self.javascript)
        self.assertIn('/app.js?v=20260908-provider-ui-v1', self.html)


if __name__ == '__main__':
    unittest.main()
