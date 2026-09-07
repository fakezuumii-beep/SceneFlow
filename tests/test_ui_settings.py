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
        self.assertIn('全局 API 配置', header)
        self.assertNotIn('id="exportButton"', header)
        self.assertIn("$('#globalApiButton').onclick=()=>guarded(openGlobalApiSettings)", self.javascript)

    def test_global_dialog_contains_deepseek_and_pexels_settings(self):
        dialog = self.html.split('<dialog id="settingsDialog">', 1)[1].split('</dialog>', 1)[0]
        for name in ('llm_base_url', 'llm_model', 'llm_api_key', 'pexels_api_key'):
            self.assertIn(f'name="{name}"', dialog)
        self.assertIn('对所有播客项目生效', dialog)
        self.assertIn('完整密钥仅保存在本机', dialog)
        self.assertIn('<details class="settings-advanced">', dialog)
        self.assertIn("?'••••••••••••':'尚未配置'", self.javascript)

    def test_export_action_remains_in_production_settings(self):
        header_end = self.html.index('</header>')
        export_position = self.html.index('id="exportButton"')
        settings_panel = self.html.index('id="setupPanel"')
        self.assertGreater(export_position, header_end)
        self.assertGreater(export_position, settings_panel)
        self.assertIn("$('#exportButton').onclick=()=>startJob('render')", self.javascript)

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
        self.assertIn('/style.css?v=20260907-quick-launch-art-v8', self.html)
        self.assertIn('.quick-launch>#quickLaunchStatus{display:none}', self.css)
        self.assertIn('filter:none', self.css)
        self.assertIn("background:url('/quick-launch-backgrounds/ready.png')", self.css)
        self.assertIn("linear-gradient(145deg,#758078a8,#aab09a8f),url('/quick-launch-backgrounds/not-ready.png')", self.css)
        self.assertIn('background-blend-mode:color', self.css)
        self.assertIn('drop-shadow(0 0 5px #83d9cb)', self.css)
        self.assertIn('filter:none', self.css)
        self.assertIn('.quick-launch #autoButton{opacity:1', self.css)


if __name__ == '__main__':
    unittest.main()
