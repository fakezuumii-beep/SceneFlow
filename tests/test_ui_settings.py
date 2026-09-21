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
                     'aroll_musetalk_quality', 'aroll_musetalk_parsing_mode',
                     'aroll_musetalk_extra_margin', 'aroll_musetalk_left_cheek_width',
                     'aroll_musetalk_right_cheek_width', 'aroll_musetalk_audio_padding_left',
                     'aroll_musetalk_audio_padding_right',
                     'aroll_latentsync_url', 'aroll_latentsync_lips_expression',
                     'aroll_latentsync_inference_steps',
                     'aroll_custom_type', 'aroll_comfyui_workflow_hash', 'aroll_external_api_key',
                     'aroll_autodl_api_key', 'aroll_autodl_resolution','aroll_autodl_cut_style',
                     'tts_seed_api_key','tts_index_url'):
            self.assertIn(f'name="{name}"', dialog)
        self.assertIn('由所有项目共用', dialog)
        self.assertIn('所有设置仅保存在本机', dialog)
        self.assertIn('<details class="settings-advanced">', dialog)
        self.assertIn('data-test-provider="llm"', dialog)
        self.assertIn('data-test-provider="broll"', dialog)
        self.assertIn('data-test-provider="aroll"', dialog)
        self.assertIn('data-test-provider="tts_seed"', dialog)
        self.assertIn('data-test-provider="tts_index"', dialog)
        self.assertIn('rel="noopener noreferrer"', dialog)
        self.assertIn("placeholder=s[key+'_configured']?'••••••••••••':'尚未配置'", self.javascript)

    def test_simple_provider_modes_hide_technical_fields_by_default(self):
        dialog = re.search(r'<dialog id="settingsDialog".*?</dialog>', self.html, re.S).group(0)
        self.assertNotIn('https://api.deepseek.com', dialog)
        self.assertNotIn('deepseek-v4-flash', dialog)
        self.assertIn('id="llmCustomFields" class="hidden"', dialog)
        self.assertIn('id="customArollFields" class="aroll-mode hidden"', dialog)
        self.assertIn("$('#llmCustomFields').classList.toggle('hidden',llm!=='custom')", self.javascript)
        self.assertIn("$('#customArollFields').classList.toggle('hidden',!['custom','infinitetalk'].includes(aroll))", self.javascript)
        self.assertIn("$('#autodlH3Fields').classList.toggle('hidden',aroll!=='autodl_h3')", self.javascript)
        self.assertIn("$('#latentsyncFields').classList.toggle('hidden',aroll!=='latentsync')", self.javascript)

    def test_home_aroll_badge_is_provider_driven(self):
        self.assertIn('id="arollBadge">人物口型</span>', self.html)
        self.assertNotIn('id="arollBadge">MuseTalk', self.html)
        self.assertIn("$('#arollBadge').textContent=status.aroll.short_name||status.aroll.name", self.javascript)

    def test_latentsync_is_the_high_quality_local_option(self):
        dialog = re.search(r'<dialog id="settingsDialog".*?</dialog>', self.html, re.S).group(0)
        self.assertIn('id="latentsyncFields"', dialog)
        self.assertIn('LatentSync 1.6', dialog)
        self.assertIn('name="aroll_latentsync_url"', dialog)
        self.assertIn('name="aroll_latentsync_lips_expression"', dialog)
        self.assertIn('name="aroll_latentsync_inference_steps"', dialog)
        self.assertIn('清晰增强 · 2.2', dialog)
        self.assertIn('精细增强 · 35 步', dialog)
        self.assertIn('适合 RTX 2080 Ti 22GB', dialog)
        self.assertIn('快速本地 · MuseTalk 1.5', dialog)

    def test_musetalk_has_real_quality_controls(self):
        dialog = re.search(r'<dialog id="settingsDialog".*?</dialog>', self.html, re.S).group(0)
        musetalk = dialog.split('id="musetalkFields"', 1)[1].split('id="wav2lipFields"', 1)[0]
        for name in ('aroll_musetalk_quality','aroll_musetalk_parsing_mode',
                     'aroll_musetalk_extra_margin','aroll_musetalk_left_cheek_width',
                     'aroll_musetalk_right_cheek_width','aroll_musetalk_audio_padding_left',
                     'aroll_musetalk_audio_padding_right'):
            self.assertIn(f'name="{name}"', musetalk)
        self.assertIn('最高质量 · FP32 + 官方人脸解析', musetalk)
        self.assertIn('安装 / 校验 MuseTalk 高质量组件', musetalk)
        self.assertIn("'aroll_musetalk_quality','aroll_musetalk_parsing_mode'", self.javascript)

    def test_autodl_automatic_lipsync_has_all_live_resolutions(self):
        dialog = re.search(r'<dialog id="settingsDialog".*?</dialog>', self.html, re.S).group(0)
        for value in ('480p竖','768p竖','1080p竖','480p横','768p横','1080p横'):
            self.assertIn(f'value="{value}"',dialog)
        self.assertIn('minimax_h3_image_audio_to_video_v2_15s',dialog)
        self.assertIn('name="aroll_autodl_cut_style"',dialog)

    def test_voice_clone_engines_and_reference_upload_are_visible(self):
        for provider in ('seed-audio','indextts25'):
            self.assertIn(f'value="{provider}"',self.html)
        self.assertIn('id="voiceReferenceUpload"',self.html)
        self.assertIn('id="playVoice"',self.html)
        self.assertIn("uploadFile('voice_reference'",self.javascript)
        self.assertIn("reference:state.project?.voice_reference||''",self.javascript)
        self.assertIn("$('#playVoice').onclick",self.javascript)
        self.assertIn('id="transcriptionDevice"',self.html)

    def test_export_action_remains_in_production_settings(self):
        header_end = self.html.index('</header>')
        export_position = self.html.index('id="exportButton"')
        settings_panel = self.html.index('id="setupPanel"')
        self.assertGreater(export_position, header_end)
        self.assertGreater(export_position, settings_panel)
        self.assertIn("$('#exportButton').onclick=()=>startJob(hasReviewCut()?'finish':'render')", self.javascript)

    def test_beginner_panel_only_keeps_episode_level_choices(self):
        panel = self.html.split('<section id="setupPanel"', 1)[1].split('</section>', 1)[0]
        self.assertIn('本期画面', panel)
        self.assertIn('A 主播、B 素材、E 证据、R 录屏、M 动效、G 生成', panel)
        self.assertIn('程序再决定内部切点、时长、素材源和渲染链路', panel)
        self.assertNotIn('data-ratio-preset', panel)
        self.assertNotIn('id="ratio"', panel)
        self.assertIn('id="subtitlesToggle"', panel)
        self.assertIn('id="aspectRatio"', panel)
        self.assertIn('value="1:1"', panel)
        self.assertIn('value="9:16"', panel)
        self.assertIn("'9:16':'9 / 16'", self.javascript)
        self.assertIn('自动 B-roll 将按新画幅重新匹配',self.javascript)
        self.assertIn('id="resolution"', panel)
        self.assertIn('高级制作设置', panel)
        self.assertIn('id="planButton"', panel)
        self.assertIn('id="materialsButton"', panel)
        self.assertNotIn('id="asrModel"', panel)
        self.assertNotIn('Whisper', panel)
        self.assertNotIn('MuseTalk', panel)
        self.assertNotIn('Pexels', panel)

    def test_auto_edit_plan_controls_are_available_without_replacing_source_timeline(self):
        panel = self.html.split('<section id="setupPanel"', 1)[1].split('</section>', 1)[0]
        for control in ('autoEditToggle','removePausesToggle','pauseThreshold','highlightToggle',
                        'cardsToggle','bgmToggle','bgmUpload','bgmVolume','generateEditPlan',
                        'editPlanSummary'):
            self.assertIn(f'id="{control}"',panel)
        self.assertIn('保留原时间线，只压缩最终成片',panel)
        self.assertIn("api('/projects/'+pid()+'/edit-plan'",self.javascript)
        self.assertIn("uploadFile('bgm'",self.javascript)
        self.assertIn('function renderEditPlan()',self.javascript)
        self.assertIn('.auto-edit-section{',self.css)

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
        self.assertIn("api('/projects/'+pid()+'/preflight?action='", self.javascript)

    def test_installer_supports_project_local_offline_runtime(self):
        installer=(ROOT/'安装工作台.ps1').read_text(encoding='utf-8')
        engine=(ROOT/'engine_setup.py').read_text(encoding='utf-8')
        portable=(ROOT/'tools'/'build-portable.ps1').read_text(encoding='utf-8')
        self.assertIn('UV_PYTHON_INSTALL_DIR',installer)
        self.assertIn(".offline\\main-wheels",installer)
        self.assertIn("OFFLINE/'media-wheels'",engine)
        self.assertIn("torch==2.8.0+cu126",engine)
        self.assertIn("'auto_edit.py'",portable)

    def test_running_pipeline_uses_the_eight_character_frames(self):
        self.assertIn('function runningPipelineStage(p)', self.javascript)
        self.assertIn("const direct={tts:0,transcribe:0,plan:1,materials:2,aroll:2,render:3,draft:2,finish:2}", self.javascript)
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
        self.assertIn('/style.css?v=20260919-five-route-v6', self.html)
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
        self.assertIn("const action=primaryAction(),oneClickGenerating=state.startingAction===action", self.javascript)
        self.assertIn("review?'继续完成'", self.javascript)
        self.assertIn("$('#storyboardPreviewButton').onclick=()=>startJob('draft')", self.javascript)
        self.assertIn('id="storyboardPreviewButton"', self.html)
        self.assertIn('分镜预览', self.html)
        self.assertIn("const currentVersionExported=p.exports.some(e=>(e.kind||'final')==='final'", self.javascript)
        self.assertIn('/app.js?v=20260919-five-route-v6', self.html)
        self.assertIn('id="cutModeSummary"', self.html)
        self.assertIn("status.aroll.id==='autodl_h3'?`语义分段 · H3 ${h3Style}`", self.javascript)
        self.assertIn("'语义分段 · A-roll 连续呈现'", self.javascript)

    def test_preview_flow_and_shot_level_controls_are_visible(self):
        panel = self.html.split('<section id="setupPanel"', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('id="workflowMode"', panel)
        self.assertNotIn('id="finishTwoStep"', panel)
        self.assertIn("const primaryAction=()=>hasReviewCut()?'finish':'all'",self.javascript)
        self.assertIn("latestExportTime('draft')>latestExportTime('final')",self.javascript)
        self.assertIn('id="shotArollProvider"', self.javascript)
        self.assertNotIn('id="shotArollPrompt"', self.javascript)
        self.assertIn('id="shotArollResolution"', self.javascript)
        self.assertIn('candidate-grid', self.javascript)
        self.assertIn('.inspector{position:sticky', self.css)

    def test_h3_prompted_workflow_has_cut_frequency_control(self):
        h3=self.html.split('id="autodlH3Fields"',1)[1].split('</div>',1)[0]
        self.assertNotIn('name="aroll_autodl_prompt"',h3)
        self.assertIn('name="aroll_autodl_cut_style"',h3)
        self.assertIn('固定长镜头 · 默认 / 不切镜',h3)
        self.assertIn('/minimax_h3_image_audio_to_video_v2_15s',h3)
        self.assertIn("'aroll_autodl_resolution','aroll_autodl_cut_style'",self.javascript)
        self.assertNotIn('.h3-default-prompt textarea',self.css)

    def test_infinitetalk_prompts_have_global_defaults_and_shot_overrides(self):
        dialog = re.search(r'<dialog id="settingsDialog".*?</dialog>', self.html, re.S).group(0)
        self.assertIn('id="infinitetalkPromptFields"',dialog)
        self.assertIn('name="aroll_infinitetalk_positive_prompt"',dialog)
        self.assertIn('name="aroll_infinitetalk_negative_prompt"',dialog)
        self.assertIn('原工作流文件不会被改写',dialog)
        self.assertIn("aroll_infinitetalk_prompt_supported!==false",self.javascript)
        self.assertIn('id="shotInfinitePositivePrompt"',self.javascript)
        self.assertIn('id="shotInfiniteNegativePrompt"',self.javascript)
        self.assertIn('相邻但提示词不同的镜头会分开生成',self.javascript)
        self.assertIn('#infinitetalkPromptFields textarea',self.css)

    def test_timeline_editor_uses_one_clock_and_lightweight_selection(self):
        self.assertIn('id="timelineScroller"', self.html)
        self.assertIn('id="timelinePlayhead"', self.html)
        self.assertIn('id="semanticTimeline"', self.html)
        self.assertIn('id="timelineZoomFit"', self.html)
        self.assertIn('function shotAt(time)', self.javascript)
        self.assertIn('function updateTimelinePosition(time,shot)', self.javascript)
        self.assertIn('requestAnimationFrame(()=>{timelineSeekAnimation=0;seek(timelineSeekValue)', self.javascript)
        self.assertIn('id="splitSemanticShot"', self.javascript)
        self.assertIn('id="mergePreviousShot"', self.javascript)
        self.assertIn("editShotStructure('merge'", self.javascript)
        self.assertIn('.timeline-playhead{position:absolute', self.css)
        selection=self.javascript.split('function selectShot(id,jump=false)',1)[1].split('function setPanel',1)[0]
        self.assertNotIn('renderTimeline()',selection)
        self.assertNotIn('renderShots()',selection)

    def test_timeline_visual_track_uses_shot_numbers_and_detail_heading_uses_dialogue(self):
        visual=self.javascript.split("$('#visualTimeline').innerHTML=",1)[1].split("const semantics=",1)[0]
        self.assertIn("const left=",visual)
        self.assertIn("role=roleOf(s),number=role+String(i+1).padStart(2,'0')",visual.replace("\\'", "'"))
        self.assertIn(">${number}</button>",visual)
        self.assertNotIn("<span> · ${esc(s.title)}</span>",visual)
        detail=self.javascript.split("const head=",1)[1].split("const common=",1)[0]
        self.assertIn("${esc(s.text||s.title)}",detail)

    def test_visual_director_exposes_six_roles_and_preserves_broll_controls(self):
        for role in ('A','B','E','R','M','G'):
            self.assertIn(f'data-filter="{role}"',self.html)
            self.assertIn(f'{role}:[' ,self.javascript.replace(' ',''))
        self.assertIn('data-visual-role="${role}"',self.javascript)
        self.assertIn('id="shotStockQuery"',self.javascript)
        self.assertIn('id="shotStockQueryAlt"',self.javascript)
        self.assertIn('stock_search_query_alt',self.javascript)
        self.assertIn('searchShot',self.javascript)
        self.assertIn('data-candidate',self.javascript)
        self.assertIn('StockAssetResolver',self.javascript)
        self.assertIn('id="resolveVisual"',self.javascript)
        self.assertIn('R 录屏（暂未实现）',self.html)
        self.assertIn('id="shotMotionData"',self.javascript)
        self.assertIn("doRequest(`/shots/${s.id}/resolve`",self.javascript)

    def test_wav2lip_install_requires_visible_third_party_acknowledgement(self):
        self.assertIn('id="wav2lipLicenseDialog"', self.html)
        self.assertIn('id="wav2lipLicenseAck" type="checkbox"', self.html)
        self.assertIn('id="wav2lipLicenseContinue" disabled', self.html)
        self.assertIn('https://github.com/Rudrabha/Wav2Lip#non-commercial-open-source-version', self.html)
        self.assertIn('rel="noopener noreferrer"', self.html)
        self.assertIn('id="wav2lipModelUpload" type="file" accept=".pt,.pth"', self.html)
        self.assertIn("if(!await requestWav2LipLicense())return", self.javascript)
        self.assertIn("api('/settings/wav2lip-license'", self.javascript)
        self.assertIn("api('/settings/wav2lip-model'", self.javascript)

    def test_morning_briefing_requires_human_confirmation(self):
        dialog = self.html.split('<dialog id="morningBriefingDialog"', 1)[1].split('</dialog>', 1)[0]
        self.assertIn('id="generateMorning"', dialog)
        self.assertIn('id="morningStories"', dialog)
        self.assertIn('id="morningConfirmCheck"', dialog)
        self.assertIn('id="confirmMorning" disabled', dialog)
        self.assertIn('不会自动生成或发布视频', dialog)
        self.assertIn("api('/morning-briefing/confirm'", self.javascript)
        self.assertIn("$('#morningConfirmCheck').checked", self.javascript)

    def test_project_delete_is_confirmed_and_recoverable(self):
        self.assertIn('id="deleteProjectButton"',self.html)
        dialog=self.html.split('<dialog id="deleteProjectDialog"',1)[1].split('</dialog>',1)[0]
        self.assertIn('id="deleteProjectConfirm"',dialog)
        self.assertIn('本机回收目录',dialog)
        self.assertIn("api('/projects/'+project.id,{method:'DELETE'})",self.javascript)
        self.assertIn("$('#deleteProjectButton').disabled=state.busy",self.javascript)


if __name__ == '__main__':
    unittest.main()
