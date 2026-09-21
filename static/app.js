'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const state={project:null,projects:[],selected:null,panel:'setup',filter:'all',inputMode:'text',busy:false,polling:false,previewKey:'',pending:0,startingAction:null,saving:Promise.resolve(),arollSupported:false,ttsStatus:null,asrModel:'base',providerCatalog:null,settingsData:null,providerStatus:null,preflight:null,morning:null,activeShotIndex:0,activeShotId:null,timelineZoom:0,lastTimeLabel:'',lastKindLabel:'',lastCaption:'',lastProjectRefresh:0};
let previewAnimation=0,timelineSeekAnimation=0,timelineSeekValue=0;
const VISUAL_ROLES={A:['A 主播','主播观点、判断与总结'],B:['B 素材','城市、办公、科技等行业说明画面'],E:['E 证据','官网、截图、报告与真实对象'],R:['R 录屏（暂未实现）','当前自动转为证据截图，失败后回主播'],M:['M 动效','数字、对比、列表与时间线'],G:['G 生成','仅在缺少真实素材时使用']};
const ACTIVE_VISUAL_ROLES=new Set(['A','B','E','M','G']);
const MOTION_TEMPLATES=[['M_TITLE','标题'],['M_COMPARE','左右对比'],['M_LIST','要点列表'],['M_TIMELINE','时间线'],['M_NUMBER','核心数据'],['M_RANKING','排行榜'],['M_PROCESS','输入到输出'],['M_GALLERY','项目画廊']];
const roleOf=s=>String(s?.visual_role||(s?.kind==='A'?'A':'B')).toUpperCase();
const roleLabel=s=>VISUAL_ROLES[roleOf(s)]?.[0]||roleOf(s);
const roleName=role=>VISUAL_ROLES[role]?.[0]||role;
const voiceCatalog={
  'azure-v1':{
    Chinese:[['zh-CN-XiaoxiaoNeural','中文女声 · 晓晓（默认）'],['zh-CN-XiaoyiNeural','中文女声 · 晓伊'],['zh-CN-liaoning-XiaobeiNeural','中文女声 · 晓北（辽宁）'],['zh-CN-shaanxi-XiaoniNeural','中文女声 · 晓妮（陕西）'],['zh-CN-XiaoxiaoMultilingualNeural-V2','中文女声 · 晓晓多语种 V2'],['zh-CN-YunjianNeural','中文男声 · 云健'],['zh-CN-YunxiNeural','中文男声 · 云希'],['zh-CN-YunxiaNeural','中文男声 · 云夏'],['zh-CN-YunyangNeural','中文男声 · 云扬']],
    English:[['en-US-AvaNeural','英文女声 · Ava'],['en-US-EmmaNeural','英文女声 · Emma'],['en-US-JennyNeural','英文女声 · Jenny'],['en-US-AndrewNeural','英文男声 · Andrew'],['en-US-BrianNeural','英文男声 · Brian'],['en-US-GuyNeural','英文男声 · Guy']]
  },
  'seed-audio':{Chinese:[['seed-reference','参考声音复刻（推荐）'],['seed-natural-female','自然中文女声'],['seed-natural-male','自然中文男声']]},
  'indextts25':{Chinese:[['index-reference','参考声音复刻']]}
};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=s=>{s=Math.max(0,Number(s)||0);return (s>=3600?Math.floor(s/3600)+':':'')+String(Math.floor(s/60)%60).padStart(2,'0')+':'+String(Math.floor(s)%60).padStart(2,'0')};
const fmtPrecise=s=>{s=Math.max(0,Number(s)||0);return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(Math.floor(s)%60).padStart(2,'0')}.${Math.floor(s*10)%10}`};
const safeURL=s=>/^https?:\/\//.test(s||'')?s:'';
const cameraLabel=s=>({medium:'中景',medium_close:'中近景',close:'近景'}[s]||s||'');
const changeLabel=s=>({hold:'保持长镜头',cut_in:'硬切近景',cut_out:'硬切远景',push_in:'硬切近景',pull_out:'硬切远景',h3_native:'H3 自主切镜',broll_insert:'短 B-roll 插入',return_primary:'回主镜头',broll:'B-roll'}[s]||s||'');
const media=name=>state.project?`/api/projects/${state.project.id}/files/${String(name).split('/').map(encodeURIComponent).join('/')}`:'';
const host=()=>media(state.project?.host_asset||state.project?.portrait_poster||state.project?.portrait||'assets/placeholder.jpg');
const hostMedia=()=>media(state.project?.host_media_asset||state.project?.portrait||'assets/placeholder.jpg');
const hostIsVideo=()=>state.project?.host_media_kind==='video';
const latestExportTime=kind=>Math.max(0,...(state.project?.exports||[]).filter(e=>(e.kind||'final')===kind).map(e=>Number(e.created_at)||0));
const hasReviewCut=()=>latestExportTime('draft')>latestExportTime('final');
const isTwoStep=()=>hasReviewCut();
const primaryAction=()=>hasReviewCut()?'finish':'all';
function toast(message){$('#toast').textContent=message;$('#toast').style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').style.display='none',5500)}
async function api(path,options={}){
  const headers=options.body instanceof FormData?{}:{'Content-Type':'application/json'};
  const response=await fetch('/api'+path,{...options,headers:{...headers,...options.headers}});
  if(!response.ok){let data;try{data=await response.json()}catch{data={detail:`请求失败 (${response.status})`}}throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail))}
  return response.json();
}
async function guarded(fn){try{return await fn()}catch(e){toast(e.message);return null}}
function pid(){return state.project.id}
function inferProvider(draft){return voiceCatalog[draft?.provider]?draft.provider:'azure-v1'}
function updateVoiceOptions(preferred){
  const provider=$('#ttsProvider').value,cloned=provider!=='azure-v1';
  if(cloned)$('#ttsLanguage').value='Chinese';$('#ttsLanguage').disabled=cloned;
  const language=$('#ttsLanguage').value,options=voiceCatalog[provider]?.[language]||[];
  $('#ttsSpeaker').innerHTML=options.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
  $('#ttsSpeaker').value=options.some(v=>v[0]===preferred)?preferred:options[0]?.[0]||'';
  $('#voiceReferenceFields').classList.toggle('hidden',!cloned);
}
function updateTtsNotice(){
  const provider=$('#ttsProvider').value,info=state.ttsStatus?.providers?.[provider];
  const reference=state.project?.voice_reference_name;
  if(provider==='seed-audio')$('#ttsNotice').textContent=(info?.ready?'豆包 SeedAudio 已配置。':'请先在「连接与设置 → 高级设置」保存 SeedAudio Key。')+(reference?' 已准备参考声音：'+reference:' 声纹复刻还需上传本期参考声音。');
  else if(provider==='indextts25')$('#ttsNotice').textContent=!info?.ready?'IndexTTS 2.5 未就绪，请启动本机 8189 的 ComfyUI。':reference?'IndexTTS 2.5 已就绪 · 已准备参考声音：'+reference:'IndexTTS 2.5 节点已就绪，还需上传本期参考声音。';
  else $('#ttsNotice').textContent=info?.ready===false?'Azure TTS V1 组件待安装，请重新运行「安装工作台.bat」。':'Azure TTS V1 · 联网配音，无需 Azure Key；生成后可直接下载，也可使用下方播放器试听。原稿会发送到微软语音服务。';
}
function arollName(){return state.providerStatus?.aroll?.short_name||state.project?.aroll_provider?.short_name||'人物口型'}
function renderProviderSummaries(){
  const status=state.providerStatus;if(!status)return;
  $('#arollBadge').textContent=status.aroll.short_name||status.aroll.name;
  $('#globalLlmSummary').textContent='跟随全局：'+status.llm.name;
  $('#globalBrollSummary').textContent='跟随全局：'+status.broll.name;
  $('#globalArollSummary').textContent='跟随全局：'+status.aroll.name;
  const h3Style={steady:'固定长镜头',restrained:'克制切镜',free:'自由切镜'}[state.settingsData?.aroll_autodl_cut_style||'steady'];
  $('#cutModeSummary').textContent=status.aroll.id==='autodl_h3'?`语义分段 · H3 ${h3Style}`:'语义分段 · A-roll 连续呈现';
}
async function loadProviderState(){
  if(!state.providerCatalog)state.providerCatalog=await api('/providers');
  const suffix=state.project?'?project_id='+encodeURIComponent(state.project.id):'';
  [state.settingsData,state.providerStatus]=await Promise.all([api('/settings'),api('/providers/status'+suffix)]);
  renderProviderSummaries();
}
async function refreshPreflight(){
  if(!state.project)return;
  try{state.preflight=await api('/projects/'+pid()+'/preflight?action='+primaryAction())}catch{state.preflight=null}
  renderStatus();
}
async function refreshProjects(){state.projects=await api('/projects');renderProjects()}
function renderProjects(){
  $('#projectCount').textContent=state.projects.length;
  $('#projects').innerHTML=state.projects.map(p=>{const running=p.job?.status==='running',sub=running?(p.job.stage==='排队中'?'排队中 · '+p.job.message:'进行中 · '+p.job.message):(p.duration?fmt(p.duration)+' · 单人播客':'等待文字 / 音频');return `<button class="project-item ${p.id===state.project?.id?'active':''} ${running?'working':''}" data-project="${p.id}"><span class="project-icon">${running?'◌':'▤'}</span><span><strong>${esc(p.name)}</strong><small>${esc(sub)}</small></span></button>`}).join('');
  $$('[data-project]').forEach(b=>b.onclick=()=>guarded(()=>openProject(b.dataset.project)));
}
async function openProject(id){
  if(state.project)await flushScript();
  await state.saving;
  $('#audioPlayer').pause();$('#brollPreview').pause();
  state.project=await api('/projects/'+id);if(!state.project.shots.length)state.panel='setup';state.selected=state.project.shots[0]?.id;state.previewKey='';state.activeShotIndex=0;state.activeShotId=null;state.timelineZoom=Number(localStorage.getItem('solo-timeline-zoom-'+id))||0;localStorage.setItem('solo-project',id);
  const audio=$('#audioPlayer');if(state.project.audio)audio.src=media(state.project.audio);else{audio.removeAttribute('src');audio.load()}
  await loadProviderState();renderAll();renderProjects();await refreshPreflight();
}
async function reload(){const p=await api('/projects/'+pid());state.project=p;if(!p.shots.some(s=>s.id===state.selected))state.selected=p.shots[0]?.id;renderAll();await refreshPreflight()}
function renderAll(){
  const p=state.project;if(!p)return;
  const player=$('#audioPlayer'),url=p.audio?media(p.audio):'';
  if(url&&player.getAttribute('src')!==url){player.src=url;player.load()}
  const draft=readDraft(p.id)||p.script||{text:'',provider:'azure-v1',speaker:'zh-CN-XiaoxiaoNeural',language:'Chinese',speed:1,...(p.script_defaults||{})};
  if(document.activeElement!==$('#scriptText'))$('#scriptText').value=draft.text;
  $('#ttsProvider').value=inferProvider(draft);
  $('#ttsLanguage').value=[...$('#ttsLanguage').options].some(o=>o.value===draft.language)?draft.language:'Chinese';
  updateVoiceOptions(draft.speaker);$('#ttsSpeed').value=String(draft.speed||1);updateTtsNotice();
  setInputMode(localStorage.getItem('solo-input-'+p.id)||(p.script||!p.audio?'text':'audio'));
  $('#playVoice').classList.toggle('hidden',!p.tts);$('#downloadVoice').classList.toggle('hidden',!p.tts);$('#downloadVoice').href=url;
  if(document.activeElement!==$('#projectName'))$('#projectName').value=p.name;
  $('#crumbTitle').textContent=p.name;
  $('#audioFilename').textContent=p.audio_name||'点击或拖入音频';$('#audioFilename').title=p.audio_name||'';
  $('#voiceReferenceLabel').textContent=p.voice_reference_name||'尚未上传；建议 10–30 秒干净人声';
  $('#portraitThumb').src=host();$('#previewEmpty').classList.toggle('hidden',!!p.audio);
  const hostVideo=$('#portraitVideo');$('#portraitThumb').classList.toggle('hidden',hostIsVideo());hostVideo.classList.toggle('hidden',!hostIsVideo());
  if(hostIsVideo()){
    const url=hostMedia();if(hostVideo.getAttribute('src')!==url){hostVideo.src=url;hostVideo.load()}
    hostVideo.play().catch(()=>{});
  }else{hostVideo.pause();hostVideo.removeAttribute('src');hostVideo.load()}
  $('#portraitLabel').textContent=p.portrait_name?`${p.portrait_name}${hostIsVideo()?' · '+Number(p.portrait_duration).toFixed(1)+' 秒 · 循环视频':' · 图片'}`:(hostIsVideo()?'SceneFlow 内置女主持 · 默认循环视频':'默认播客主持人 · 单人正脸清晰');
  $('#totalTime').textContent=fmt(p.duration);$('#scrubber').max=p.duration||100;
  const aspect=p.options.aspect_ratio||'16:9';const preview=$('#preview');$('#aspectRatio').value=aspect;$('#aspectRatioLabel').textContent=aspect;preview.style.aspectRatio={'1:1':'1 / 1','9:16':'9 / 16'}[aspect]||'16 / 9';preview.classList.toggle('portrait',aspect==='9:16');
  $('#resolution').value=p.options.resolution;$('#subtitlesToggle').checked=p.options.subtitles;
  $('#autoEditToggle').checked=!!p.options.auto_edit_enabled;$('#removePausesToggle').checked=!!p.options.auto_edit_remove_pauses;
  $('#pauseThreshold').value=String(p.options.auto_edit_pause_threshold??.65);$('#highlightToggle').checked=!!p.options.auto_edit_highlights;$('#cardsToggle').checked=!!p.options.auto_edit_cards;
  $('#bgmToggle').checked=!!p.options.bgm_enabled;$('#bgmVolume').value=String(p.options.bgm_volume??.14);$('#bgmLabel').textContent=p.bgm_name||'尚未选择音乐';
  renderProviderSummaries();renderEditPlan();
  const transcription=p.transcription?.engine||'';$('#transcriptionDevice').textContent=transcription?`本期转录：${/\/ cuda/i.test(transcription)?'CUDA GPU':/\/ cpu/i.test(transcription)?'CPU':'已完成'} · ${transcription}`:'本期还没有运行语音转录。';
  $('#downloadSrt').classList.toggle('hidden',!p.segments.length);$('#downloadSrt').href='/api/projects/'+pid()+'/subtitles';
  renderPipeline();renderStatus();renderTimeline();renderShots();renderShotDetail();renderExports();setPanel(state.panel);syncPreview();
}
function runningPipelineStage(p){
  const j=p?.job;if(j?.status!=='running')return -1;
  const direct={tts:0,transcribe:0,plan:1,materials:2,aroll:2,render:3,draft:2,finish:2};
  if(j.action!=='all')return direct[j.action]??-1;
  const stage=String(j.stage||'');
  if(['文字配音','本地转录','转录'].includes(stage))return 0;
  if(['语义判断','语义分镜','规则剪辑'].includes(stage))return 1;
  if(['匹配素材','A-roll 对口型'].includes(stage))return 2;
  if(['合成视频','校验输出'].includes(stage))return 3;
  return 0;
}
function renderPipeline(){
  const p=state.project,b=p.shots.filter(s=>s.kind==='B'),ready=b.filter(s=>s.asset).length,a=p.shots.filter(s=>s.kind==='A'),aReady=a.filter(s=>s.aroll_ready).length;
  const two=isTwoStep()||p.job?.action==='draft',draft=hasReviewCut(),finalReady=p.exports.some(e=>(e.kind||'final')==='final'&&e.revision===p.revision);
  const stages=[['文字 / 音频',p.audio?fmt(p.duration)+' · 已就绪':'声音是故事的起点',!!p.audio],['理解与分镜',p.shots.length?`${p.narrative_segments?.length||0} 个叙事段 · ${p.shots.length} 个视觉镜头`:p.segments.length?`${p.segments.length} 个候选段 · 待判断`:'时间戳 · 语义分类',!!p.shots.length],['匹配画面',p.shots.length?(two&&!draft?`参考图占位 · 素材 ${ready}/${b.length}`:`口型 ${aReady}/${a.length} · 素材 ${ready}/${b.length}`):'人物口型 · 场景素材',!!p.shots.length&&ready===b.length&&(two||aReady===a.length)],['导出成片',finalReady?'完整成片已导出':two&&draft?'正在逐镜精修':'预览 · 字幕 · MP4',finalReady]];
  const next=stages.findIndex(s=>!s[2]),running=runningPipelineStage(p);
  $('#pipeline').innerHTML=stages.map((s,i)=>{const working=i===running;return `<div class="pipeline-step ${s[2]?'done':i===next?'current':''} ${working?'running':''}"><span class="pipeline-number">${s[2]?'✓':String(i+1).padStart(2,'0')}</span><div class="pipeline-copy"><strong>${s[0]}</strong><small>${esc(s[1])}</small></div>${working?`<span class="pipeline-worker" role="img" aria-label="${s[0]}正在运行"><img src="/pipeline-animations/step${i+1}-frame1.png" alt=""><img src="/pipeline-animations/step${i+1}-frame2.png" alt=""></span>`:''}</div>`}).join('');
}
function renderStatus(){
  const p=state.project,j=p.job;state.busy=j?.status==='running'||state.pending>0||!!state.startingAction;
  $('#deleteProjectButton').disabled=state.busy;
  $('#serviceNotice').classList.toggle('hidden',state.arollSupported);
  $('#serviceNotice').textContent='工作台有更新尚未载入。请运行目录中的「重启工作台.bat」，页面将自动检查更新状态，项目和已生成内容会保留。';
  const noB=p.shots.length&&!p.shots.some(s=>s.kind==='B');
  $('#planNotice').classList.toggle('hidden',!noB);
  $('#planNotice').textContent='语义判断认为本次不需要 B-roll，因此保留了连续人物画面。你也可在镜头详情中手动改为 B-roll。';
  document.body.classList.toggle('busy',state.busy);
  const show=!!j;$('#statusbar').classList.toggle('hidden',!show);
  if(show){$('#statusbar').classList.toggle('error',['error','cancelled'].includes(j.status));$('#statusbar .status-message').textContent=j.message;$('#statusbar .progress i').style.width=j.progress+'%';$('#cancelJob').classList.toggle('hidden',j.status!=='running');$('#statusbar .progress').classList.toggle('hidden',j.status!=='running')}
  const sourceReady=!!(p.audio||$('#scriptText').value.trim()),activeIssues=(state.preflight?.issues||[]).filter(issue=>!(sourceReady&&issue.code==='source')),providersReady=!activeIssues.length,previewReady=sourceReady&&state.arollSupported&&!activeIssues.some(issue=>issue.code!=='aroll'),launchReady=sourceReady&&state.arollSupported&&providersReady,launch=$('#quickLaunch');
  const action=primaryAction(),oneClickGenerating=state.startingAction===action||(j?.status==='running'&&j.action===action),previewGenerating=state.startingAction==='draft'||(j?.status==='running'&&j.action==='draft');
  const currentVersionExported=p.exports.some(e=>(e.kind||'final')==='final'&&e.revision===p.revision),review=hasReviewCut();
  launch.classList.toggle('pending',!launchReady);
  launch.classList.toggle('generating',oneClickGenerating);
  $('#autoButton').innerHTML=`<span>${oneClickGenerating?'…':'✦'}</span> ${oneClickGenerating?'正在生成':review?'继续完成':currentVersionExported?'重新生成':'一键生成播客'}`;
  $('#storyboardPreviewButton').textContent=previewGenerating?'正在生成分镜预览…':'分镜预览';
  if(state.busy){$('#quickLaunchStatus').textContent=oneClickGenerating?'正在生成':'正在处理中';$('#quickLaunchHelp').textContent=j?.message||'当前任务完成后即可继续。'}
  else if(launchReady){$('#quickLaunchStatus').textContent=currentVersionExported?'当前版本已生成':'准备就绪后';$('#quickLaunchHelp').textContent=review?'分镜预览已完成；调整镜头后点“继续完成”生成 A-roll 和完整成片':(currentVersionExported?'再次点击会为当前版本重新生成成片':'一键完整生成，或先用“分镜预览”检查画面与节奏')}
  else{const missing=[];if(!sourceReady)missing.push('输入文稿或导入音频');if(!state.arollSupported)missing.push('重启工作台载入更新');if(sourceReady&&activeIssues.length)missing.push(activeIssues[0].message.replace(/^还差一步[：:]\s*/,''));$('#quickLaunchStatus').textContent='尚未准备就绪';$('#quickLaunchHelp').textContent='还差：'+missing.join('；')}
  $('#autoButton').disabled=!launchReady||state.busy;$('#storyboardPreviewButton').disabled=!previewReady||state.busy;$('#exportButton').disabled=!p.shots.length||state.busy||!state.arollSupported;
  $('#exportButton').textContent=review?'继续完成并导出':p.options.auto_edit_enabled?'导出精剪版 ↗':'导出视频 ↗';
  $('#ttsButton').disabled=!$('#scriptText').value.trim()||state.busy||!state.arollSupported;
  $('#scriptText').disabled=state.busy;$('#installAroll').disabled=state.busy;$('#installWav2lip').disabled=state.busy;
  $('#transcribeButton').disabled=!p.audio||state.busy||!state.arollSupported;$('#planButton').disabled=!p.segments.length||state.busy||!state.arollSupported;$('#materialsButton').disabled=!p.shots.some(s=>s.kind==='B')||state.busy||!state.arollSupported;
  $('#generateEditPlan').disabled=!p.audio||!p.shots.length||state.busy;$('#pauseThreshold').disabled=state.busy||!$('#removePausesToggle').checked;
  $('#useHostMaterial').disabled=state.busy||!$('#hostMaterial').value;
  $('#resumeJob').classList.toggle('hidden',!['error','cancelled'].includes(j?.status));
  $('#resumeJob').disabled=state.busy||!state.arollSupported;
  $('#playButton').disabled=!p.audio;$$('#shotPanel button, #shotPanel input, #shotPanel textarea, #setupPanel select, #quickStart select, #subtitlesToggle, #autoEditToggle, #removePausesToggle, #highlightToggle, #cardsToggle, #projectName, #audioUpload, #portraitUpload, #srtUpload, #bgmUpload').forEach(e=>e.disabled=state.busy);
  renderEditPlan();
}
function renderTimeline(){
  const p=state.project,scroller=$('#timelineScroller'),canvas=$('#timelineCanvas'),label=54,viewport=Math.max(320,scroller.clientWidth||700);
  const fit=Math.max(1,(viewport-label)/Math.max(.1,p.duration)),pps=state.timelineZoom||fit,width=Math.max(viewport,Math.round(label+p.duration*pps));
  canvas.style.width=width+'px';canvas.dataset.pps=String(pps);
  const ticks=Math.max(5,Math.min(13,Math.floor((width-label)/105)+1));
  $('#ruler').innerHTML=Array.from({length:ticks},(_,i)=>`<span class="timeline-tick" style="left:${i/(ticks-1)*100}%">${fmt(p.duration*i/(ticks-1))}</span>`).join('');
  $('#visualTimeline').innerHTML=p.shots.map((s,i)=>{const left=s.start/Math.max(.001,p.duration)*100,w=(s.end-s.start)/Math.max(.001,p.duration)*100,role=roleOf(s),number=role+String(i+1).padStart(2,'0');return `<button title="${esc(s.text||s.title)} · ${fmt(s.start)}–${fmt(s.end)}" aria-label="${esc(number)} · ${esc(roleName(role))} · ${esc(s.text||s.title)}" class="timeline-clip role-${role.toLowerCase()} ${role!=='A'?'b':''} ${s.id===state.selected?'selected':''} ${s.id===state.activeShotId?'playing':''}" style="left:${left}%;width:${w}%" data-seek="${s.id}">${number}</button>`}).join('');
  const semantics=(p.narrative_segments?.length?p.narrative_segments:p.candidate_segments)||[];
  $('#semanticTimeline').innerHTML=semantics.map(s=>{const start=Math.max(0,Number(s.start)||0),end=Math.min(p.duration,Number(s.end)||start),left=start/Math.max(.001,p.duration)*100,w=(end-start)/Math.max(.001,p.duration)*100;return `<button class="semantic-cue" style="left:${left}%;width:${w}%" data-semantic-time="${start}" title="${esc(s.semantic_type||'语义')} · ${esc(s.text)}">${esc(s.visual_subject||s.text||s.semantic_type||'语义')}</button>`}).join('');
  $('#waveform').innerHTML=(p.waveform||[]).map(v=>`<i style="height:${Math.max(6,v*100)}%"></i>`).join('');
  $$('[data-seek]').forEach(b=>b.onclick=e=>{e.stopPropagation();selectShot(b.dataset.seek,true)});
  $$('[data-semantic-time]').forEach(b=>b.onclick=e=>{e.stopPropagation();const t=Number(b.dataset.semanticTime);const shot=shotAt(t);if(shot)selectShot(shot.id,false);seek(t)});
  canvas.onpointerdown=e=>{if(!p.audio||e.button!==0||e.target.closest('button'))return;const update=event=>{const rect=canvas.getBoundingClientRect(),x=Math.min(rect.right,Math.max(rect.left+label,event.clientX));timelineSeekValue=(x-rect.left-label)/Math.max(1,rect.width-label)*p.duration;if(!timelineSeekAnimation)timelineSeekAnimation=requestAnimationFrame(()=>{timelineSeekAnimation=0;seek(timelineSeekValue)})};canvas.setPointerCapture(e.pointerId);update(e);canvas.onpointermove=update;canvas.onpointerup=canvas.onpointercancel=()=>{canvas.onpointermove=null;canvas.onpointerup=null;canvas.onpointercancel=null}};
  const changeZoom=factor=>{const current=state.timelineZoom||fit,next=Math.max(fit,Math.min(160,current*factor));state.timelineZoom=Math.abs(next-fit)<.5?0:next;localStorage.setItem('solo-timeline-zoom-'+p.id,String(state.timelineZoom));renderTimeline();ensureTimeVisible($('#audioPlayer').currentTime||0)};
  $('#timelineZoomIn').onclick=()=>changeZoom(1.5);$('#timelineZoomOut').onclick=()=>changeZoom(1/1.5);$('#timelineZoomFit').onclick=()=>{state.timelineZoom=0;localStorage.removeItem('solo-timeline-zoom-'+p.id);renderTimeline()};
  updateTimelinePosition($('#audioPlayer').currentTime||0,shotAt($('#audioPlayer').currentTime||0));
}
function renderShots(){
  const p=state.project;$('#shotCount').textContent=p.shots.length+' 个镜头';const visible=p.shots.filter(s=>state.filter==='all'||roleOf(s)===state.filter);
  if(!visible.length){$('#shotList').innerHTML=`<div class="empty-shots"><strong>${p.shots.length?'这个分类还没有镜头':'镜头会从你的讲述里自然生长。'}</strong>${p.shots.length?'切换到「全部」查看其他镜头。':'先输入文字生成配音，或导入音频后转录，再生成语义分镜。<br>LLM 理解语义，程序保留连续表达与真实时长。'}</div>`;return}
  $('#shotList').innerHTML=visible.map(s=>{
    const i=p.shots.indexOf(s),role=roleOf(s),missing=role==='A'?!s.aroll_ready:role==='M'?false:!s.asset;
    let thumb=role==='A'?(s.aroll_ready?`<video class="shot-thumb" src="${media(s.aroll_asset)}#t=0.1" muted preload="metadata" aria-label="${esc(arollName())} 人物口型"></video>`:`<img class="shot-thumb" src="${host()}" alt="人物出镜">`):s.asset?(/\.(jpg|png|webp)$/i.test(s.asset)?`<img class="shot-thumb" src="${media(s.asset)}" alt="${role} 视觉素材">`:`<video class="shot-thumb" src="${media(s.asset)}#t=0.1" muted preload="metadata" aria-label="${role} 视觉素材"></video>`):role==='M'?`<img class="shot-thumb" src="${host()}" alt="动效模板底图">`:`<div class="shot-thumb">${role==='E'?'证据待补':role==='R'?'录屏待补':role==='G'?'生成待补':role==='B'?'素材待补':'视觉待补'}</div>`;
    const ready=role==='A'?'口型已就绪':role==='M'?'动效已规划':role==='E'?(s.asset?'证据已匹配':'证据待补'):role==='R'?(s.asset?'录屏已匹配':'录屏待补'):role==='G'?(s.asset?'生成镜头已匹配':'生成待补'):role==='B'?'素材已匹配':'已匹配';
    return `<article class="shot-card ${s.id===state.selected?'selected':''} ${s.id===state.activeShotId?'playing':''}" data-shot="${s.id}" tabindex="0" role="button" aria-label="镜头 ${i+1} ${esc(s.title)}"><span class="shot-number">${String(i+1).padStart(2,'0')}</span>${thumb}<div class="shot-content"><div class="shot-meta"><span class="kind-badge role-${role.toLowerCase()} ${role!=='A'?'b':''}">${esc(roleName(role))}</span><span>${fmt(s.start)} — ${fmt(s.end)}</span><span>${(s.end-s.start).toFixed(1)}s</span></div><h4>${esc(s.title)}</h4><p>${esc(s.text)}</p></div><span class="shot-state ${missing?'missing':''}">${missing?(role==='A'?'待生成口型':role==='E'?'待补证据':role==='R'?'待录屏':role==='G'?'待生成':role==='B'?'待匹配':'待补素材'):ready} ↗</span></article>`;
  }).join('');
  $$('[data-shot]').forEach(card=>{card.onclick=()=>selectShot(card.dataset.shot,true);card.onkeydown=e=>{if(e.key==='Enter')selectShot(card.dataset.shot,true)}});
}
function updateSelectionUI(){
  $$('[data-seek],[data-shot]').forEach(el=>el.classList.toggle('selected',el.dataset.seek===state.selected||el.dataset.shot===state.selected));
}
function ensureTimeVisible(time){const scroller=$('#timelineScroller'),canvas=$('#timelineCanvas');if(!scroller||!canvas||canvas.clientWidth<=scroller.clientWidth)return;const x=54+Math.max(0,Math.min(1,time/Math.max(.001,state.project.duration)))*(canvas.clientWidth-54),margin=scroller.clientWidth*.18;if(x<scroller.scrollLeft+margin)scroller.scrollLeft=Math.max(0,x-margin);else if(x>scroller.scrollLeft+scroller.clientWidth-margin)scroller.scrollLeft=x-scroller.clientWidth+margin}
function selectShot(id,jump=false){state.selected=id;state.panel='shot';updateSelectionUI();renderShotDetail();setPanel('shot');if(jump){const s=state.project.shots.find(s=>s.id===id);if(s){seek(s.start);ensureTimeVisible(s.start)}}}
function setPanel(name){state.panel=name;['setup','shot','exports'].forEach(n=>$('#'+n+'Panel').classList.toggle('hidden',n!==name));$$('[data-panel]').forEach(b=>b.classList.toggle('active',b.dataset.panel===name))}
function renderShotDetail(){
  const p=state.project,s=p.shots.find(s=>s.id===state.selected),root=$('#shotPanel');
  if(!s){root.innerHTML='<div class="panel-empty">选择一个分镜，<br>查看语义与素材详情。</div>';return}
  const i=p.shots.indexOf(s),video=s.asset&&/\.(mp4|mov|mkv|webm|m4v)$/i.test(s.asset),looped=s.source?.duration>0&&s.source.duration-(s.media_start||0)<s.end-s.start;
  const framing=[cameraLabel(s.camera),changeLabel(s.visual_change)].filter(Boolean).join(' · '),cut=s.cut_reason?`· 切点：${esc(s.cut_reason)}${Number.isFinite(s.cut_score)?` (${s.cut_score})`:''}`:'';
  const sameSettings=(a,b)=>a&&b&&a.kind===b.kind&&roleOf(a)===roleOf(b)&&(a.kind!=='A'||JSON.stringify(a.aroll_config||{})===JSON.stringify(b.aroll_config||{}));
  const previous=p.shots[i-1],next=p.shots[i+1],canPrevious=sameSettings(previous,s),canNext=sameSettings(s,next);
  const splitPoints=[...(p.candidate_segments||[]),...(p.narrative_segments||[])].map(x=>Number(x.start)).filter((v,n,a)=>Number.isFinite(v)&&v>=s.start+.5&&v<=s.end-.5&&a.indexOf(v)===n);
  const editActions=`<div class="shot-edit-actions"><button id="mergePreviousShot" class="button" ${canPrevious?'':'disabled'}>← 与前镜合并</button><button id="splitSemanticShot" class="button" ${splitPoints.length?'':'disabled'}>在播放头附近拆分</button><button id="mergeNextShot" class="button" ${canNext?'':'disabled'}>与后镜合并 →</button></div><p class="shot-edit-help">拆分会吸附到最近的真实句意边界；合并只开放给同类连续镜头。</p>`;
  const currentRole=roleOf(s);
  const head=`<div class="inspector-shot-head"><div class="eyebrow">VISUAL SHOT ${String(i+1).padStart(2,'0')} ${isTwoStep()?'<span class="phase-pill">逐镜精修</span>':''}</div><h3 class="detail-title">${esc(s.text||s.title)}</h3><div class="detail-info">${fmt(s.start)} — ${fmt(s.end)} · ${(s.end-s.start).toFixed(2)} 秒${framing?' · '+esc(framing):''}</div></div>${editActions}<div class="visual-role-row">${Object.entries(VISUAL_ROLES).map(([role,meta])=>`<button class="button role-${role.toLowerCase()} ${currentRole===role?'active':''}" data-visual-role="${role}" title="${esc(meta[1])}" ${ACTIVE_VISUAL_ROLES.has(role)?'':'disabled'}>${esc(meta[0])}</button>`).join('')}</div>`;
  const common=`<div class="detail-text">${esc(s.text)}</div><label class="detail-field">镜头标题<input id="shotTitle" value="${esc(s.title)}"></label><label class="detail-field">程序决策说明<textarea id="shotReason">${esc(s.reason)}</textarea></label><label class="detail-field">与下一镜头的交界（秒）<input id="shotEnd" type="number" step="0.01" value="${s.end}" ${i===p.shots.length-1?'disabled':''}></label><p class="source-note">修改交界会同时调整相邻镜头，总时长保持不变。语义：${esc(s.semantic_type||'—')} · 视觉价值：${Number.isFinite(s.visual_value)?s.visual_value:'—'} · 人物价值：${Number.isFinite(s.host_value)?s.host_value:'—'} · 可视化对象：${esc(s.visual_subject||'无')} ${cut}</p>`;
  const roleFields=currentRole==='B'
    ?`<div class="role-config"><h4>普通说明素材</h4><label class="detail-field">主搜索词<input id="shotStockQuery" value="${esc(s.stock_search_query||(s.keywords||[])[0]||'')}" placeholder="例如 AI office working computer"></label><label class="detail-field">备选搜索词（每行一个）<textarea id="shotStockQueryAlt">${esc((s.stock_search_query_alt||[]).join('\n'))}</textarea></label><p class="provider-inline-note">Visual Director 只标记 B；实际由 StockAssetResolver 选择当前库存素材源（Pexels / Pixabay / 未来本地库存库），画幅：${esc(p.options.aspect_ratio)}。</p></div>`
    :currentRole==='E'
    ?`<div class="role-config"><h4>真实证据</h4><label class="detail-field">证据对象<input id="shotEvidenceTarget" value="${esc(s.evidence_target||s.visual_subject||'')}" placeholder="例如 OpenAI GPT-X 官方公告"></label><label class="detail-field">证据检索词<input id="shotSearchQuery" value="${esc(s.search_query||'')}" placeholder="官方英文名称，优先保留品牌与产品名"></label><label class="detail-field">指定网页（可选）<input id="shotEvidenceUrl" value="${esc(s.evidence_url||'')}" placeholder="留空则自动搜索官网、官方Blog或GitHub"></label><div class="two-cols"><label class="detail-field">焦点 X<input id="evidenceFocusX" type="number" min="0" max="1" step="0.01" value="${esc(s.evidence_focus?.x??0)}"></label><label class="detail-field">焦点 Y<input id="evidenceFocusY" type="number" min="0" max="1" step="0.01" value="${esc(s.evidence_focus?.y??0)}"></label></div><label class="detail-field">证据缩放<input id="evidenceZoom" type="number" min="1" max="1.35" step="0.01" value="${esc(s.evidence_zoom??1.05)}"></label><button id="resolveVisual" class="button wide">重新搜索证据 / 截图</button><p class="provider-inline-note">按官网、官方Blog、官方GitHub、产品页优先排序；截图后生成稳定的竖屏证据画面，不使用容易抖动的推拉。</p></div>`
    :currentRole==='R'
      ?`<div class="role-config"><h4>录屏配置</h4><label class="detail-field">录屏目标<input id="shotRecordingTarget" value="${esc(s.recording_target||'')}" placeholder="例如 OpenAI 官网 API 入口"></label><label class="detail-field">操作说明<textarea id="shotRecordingInstruction">${esc(s.recording_instruction||'')}</textarea></label><p class="provider-inline-note">当前版本支持手动上传录屏；未上传时成片使用人物图占位，不回退泛素材。</p></div>`
      :currentRole==='M'
        ?`<div class="role-config"><h4>Motion 动效</h4><label class="detail-field">模板<select id="shotMotionType">${MOTION_TEMPLATES.map(([value,label])=>`<option value="${value}" ${String(s.motion_type||'')===value?'selected':''}>${value} · ${label}</option>`).join('')}</select></label><label class="detail-field">motion_data JSON<textarea id="shotMotionData">${esc(JSON.stringify(s.motion_data||s.motion_plan?.props||{},null,2))}</textarea></label><button id="resolveVisual" class="button wide">重新渲染动效</button><p class="provider-inline-note">模板只读取结构化参数，生成统一 Timeline 视频片段；不会让模型动态写 React 代码。</p></div>`
        :currentRole==='G'
          ?`<div class="role-config"><h4>AI 生成镜头</h4><label class="detail-field">生成模型<input id="shotGenerationModel" value="${esc(s.generation_model||'MiniMax H3 原始多参')}" readonly></label><label class="detail-field">生成 Prompt<textarea id="shotGenerationPrompt">${esc(s.generation_prompt||s.generation_concept||'')}</textarea></label><label class="detail-field">主参考图（可选）<input id="shotReferenceImage" value="${esc(s.reference_image||'')}"></label><label class="button wide">追加参考图 ${Number((s.reference_images||[]).length)}/9<input id="shotReferenceUpload" type="file" accept="image/png,image/jpeg,image/webp" hidden></label><label class="button wide">追加参考音频 ${Number((s.reference_audios||[]).length)}/2<input id="shotReferenceAudioUpload" type="file" accept="audio/*,.wav,.mp3,.m4a,.flac" hidden></label><button id="resolveVisual" class="button wide">调用 MiniMax H3 多参重新生成</button><p class="provider-inline-note">G 使用原始 H3 多参工作流，可提交最多 9 张参考图和 2 条附加参考音频；不调用 A-roll 对口型 Prompt。</p></div>`
          :'';
  if(s.kind==='B'){
    const candidates=currentRole==='B'?(s.candidates||[]).slice().sort((a,b)=>Number(b.id===s.source?.id)-Number(a.id===s.source?.id)).slice(0,3):[];
    const choices=candidates.length?`<div class="candidate-grid">${candidates.map(c=>`<div class="candidate choice ${s.source?.id===c.id?'current':''}">${safeURL(c.thumbnail)?`<img src="${esc(c.thumbnail)}" alt="${esc(c.query)}" loading="lazy" referrerpolicy="no-referrer">`:''}<div class="candidate-info"><small>${esc(c.provider)} · ${Number(c.duration||0).toFixed(1)} 秒 · ${c.width}×${c.height}</small><small>${esc(c.author)} / ${esc(c.query)}</small><button class="button" data-candidate="${esc(c.id)}">${s.source?.id===c.id?'✓ 当前使用':'选用'}</button> ${safeURL(c.page)?`<a href="${esc(c.page)}" class="source-link" target="_blank" rel="noreferrer">详情 ↗</a>`:''}</div></div>`).join('')}</div>`:currentRole==='B'?`<div class="candidate-empty">还没有候选画面<br><button id="searchShot" class="button small">搜索 3 个库存素材</button></div>`:`<div class="candidate-empty">${currentRole==='M'?'这一镜由 Motion 模板生成':currentRole==='R'?'请导入目标录屏':'请导入官方截图、产品或网页素材'}</div>`;
    root.innerHTML=head+roleFields+`${s.editorial_review?`<p class="help export-warning">${esc(s.editorial_review)}</p>`:''}${currentRole==='B'?`<div class="candidate-picker-head"><strong>候选素材</strong>${candidates.length?'<button id="refreshCandidates" class="text-button">重新搜索</button>':''}</div>`:''}${choices}${!s.asset&&!['M'].includes(currentRole)?`<p class="export-warning help">尚未匹配专用素材，成片暂用人物图；${esc(s.material_error||'可手动导入或等待后续解析')}</p>`:''}${looped?'<p class="help export-warning">此素材短于镜头时长，成片会循环使用该片段。</p>':''}<details class="shot-advanced"><summary>展开详细调整</summary>${common}<label class="detail-field">素材检索词（每行一个）<textarea id="shotKeywords">${esc((s.keywords||[]).join('\n'))}</textarea></label>${currentRole==='B'?'<button id="searchShotAdvanced" class="button wide">按新检索词搜索</button>':''}<label class="button wide">导入本地视频 / 图片<input id="localBroll" type="file" accept="video/*,image/png,image/jpeg,image/webp" hidden></label>${video?`<label class="detail-field">素材入点（秒）<input id="mediaStart" type="number" step="0.1" min="0" value="${s.media_start||0}"></label>`:''}${s.source?`<p class="source-note">当前素材：${esc(s.source.provider)} · ${esc(s.source.author||s.source.name||'')}</p>`:''}</details>`;
  }else{
    const cfg=s.aroll_config||{},selected=cfg.provider||'global',effective=s.aroll_effective_provider?.id||state.providerStatus?.aroll?.id||'latentsync';
    const providerOptions=(state.providerCatalog?.aroll||[]).map(x=>`<option value="${esc(x.id)}" ${selected===x.id?'selected':''}>${esc(x.name)}</option>`).join('');
    const resolutions=['480p竖','768p竖','1080p竖','480p横','768p横','1080p横'];
    const infinitePromptSupported=effective==='infinitetalk'&&state.settingsData?.aroll_infinitetalk_prompt_supported!==false;
    const providerFields=effective==='autodl_h3'
      ?`<label class="detail-field">H3 输出分辨率<select id="shotArollResolution"><option value="">跟随默认</option>${resolutions.map(v=>`<option value="${v}" ${cfg.resolution===v?'selected':''}>${v}</option>`).join('')}</select></label><p class="provider-inline-note">MiniMax H3 自动对口型使用固定工作流，不接收提示词。</p>`
      :infinitePromptSupported
        ?`<label class="detail-field">本镜头正向提示词<textarea id="shotInfinitePositivePrompt" maxlength="4000" placeholder="留空则跟随连接与设置里的默认提示词">${esc(cfg.positive_prompt||'')}</textarea></label><label class="detail-field">本镜头负向提示词<textarea id="shotInfiniteNegativePrompt" maxlength="4000" placeholder="留空则跟随连接与设置里的默认提示词">${esc(cfg.negative_prompt||'')}</textarea></label><p class="provider-inline-note">只覆盖这一段连续 A-roll；相邻但提示词不同的镜头会分开生成。</p>`
        :`<p class="provider-inline-note">这个工具使用固定工作流；可在「连接与设置」修改它的默认连接。</p>`;
    root.innerHTML=head+`<p class="help">当前使用：${esc(s.aroll_effective_provider?.name||arollName())}。${s.aroll_ready?'这一镜 A-roll 已就绪。':isTwoStep()?'分镜预览阶段继续使用参考图；调整完成后点“继续完成”。':'导出前会自动生成。'}</p>${s.aroll_error?`<p class="help export-warning">${esc(s.aroll_error)}</p>`:''}<div class="aroll-config"><h4>本镜头生成设置</h4><label class="detail-field">生成工具<select id="shotArollProvider"><option value="global" ${selected==='global'?'selected':''}>跟随「连接与设置」默认</option>${providerOptions}</select></label>${providerFields}${['musetalk','wav2lip'].includes(effective)?`<label class="detail-field">显存 / 批量档位<select id="shotArollBatch"><option value="">跟随默认</option>${[1,2,4,8,16].map(v=>`<option value="${v}" ${Number(cfg.batch_size)===v?'selected':''}>${v}</option>`).join('')}</select></label>`:''}</div><details class="shot-advanced"><summary>展开镜头文字与时间调整</summary>${common}</details>${!isTwoStep()?`<button id="generateShotAroll" class="button wide">${s.aroll_ready?'重新生成这一镜口型':'生成这一镜口型'}</button><p class="help">只使用 ${fmt(s.start)}–${fmt(s.end)} 的对应原音频；历史视频会保留。</p>`:'<p class="help">调整会自动保存。完成后点击上方“继续完成”，统一生成 A-roll 并导出完整成片。</p>'}`;
  }
  $$('[data-visual-role]').forEach(b=>b.onclick=()=>patchShot({visual_role:b.dataset.visualRole}));
  if($('#mergePreviousShot'))$('#mergePreviousShot').onclick=()=>editShotStructure('merge',{direction:'previous'});
  if($('#mergeNextShot'))$('#mergeNextShot').onclick=()=>editShotStructure('merge',{direction:'next'});
  if($('#splitSemanticShot'))$('#splitSemanticShot').onclick=()=>{const audio=$('#audioPlayer'),time=audio.currentTime>s.start&&audio.currentTime<s.end?audio.currentTime:(s.start+s.end)/2;editShotStructure('split',{time})};
  if($('#shotTitle'))$('#shotTitle').onchange=e=>patchShot({title:e.target.value});if($('#shotReason'))$('#shotReason').onchange=e=>patchShot({reason:e.target.value});if($('#shotEnd'))$('#shotEnd').onchange=e=>patchShot({end:Number(e.target.value)});
  if(s.kind==='B'){
    if($('#shotEvidenceTarget'))$('#shotEvidenceTarget').onchange=e=>patchShot({evidence_target:e.target.value});
    if($('#shotSearchQuery'))$('#shotSearchQuery').onchange=e=>patchShot({search_query:e.target.value,keywords:[e.target.value].filter(Boolean)});
    if($('#shotEvidenceUrl'))$('#shotEvidenceUrl').onchange=e=>patchShot({evidence_url:e.target.value});
    if($('#evidenceFocusX')||$('#evidenceFocusY')){const saveFocus=()=>patchShot({evidence_focus:{x:Number($('#evidenceFocusX')?.value||0),y:Number($('#evidenceFocusY')?.value||0),width:1,height:1}});$('#evidenceFocusX').onchange=saveFocus;$('#evidenceFocusY').onchange=saveFocus}
    if($('#evidenceZoom'))$('#evidenceZoom').onchange=e=>patchShot({evidence_zoom:Number(e.target.value)||1.05});
    if($('#shotStockQuery'))$('#shotStockQuery').onchange=e=>patchShot({stock_search_query:e.target.value,keywords:[e.target.value].filter(Boolean)});
    if($('#shotStockQueryAlt'))$('#shotStockQueryAlt').onchange=e=>patchShot({stock_search_query_alt:e.target.value.split('\n').map(x=>x.trim()).filter(Boolean)});
    if($('#shotRecordingTarget'))$('#shotRecordingTarget').onchange=e=>patchShot({recording_target:e.target.value});
    if($('#shotRecordingInstruction'))$('#shotRecordingInstruction').onchange=e=>patchShot({recording_instruction:e.target.value});
    if($('#shotMotionType'))$('#shotMotionType').onchange=e=>patchShot({motion_type:e.target.value});
    if($('#shotMotionData'))$('#shotMotionData').onchange=e=>{try{patchShot({motion_data:JSON.parse(e.target.value||'{}')})}catch{toast('motion_data 不是有效 JSON')}};
    if($('#shotGenerationModel'))$('#shotGenerationModel').onchange=e=>patchShot({generation_model:e.target.value});
    if($('#shotGenerationPrompt'))$('#shotGenerationPrompt').onchange=e=>patchShot({generation_prompt:e.target.value});
    if($('#shotReferenceImage'))$('#shotReferenceImage').onchange=e=>patchShot({reference_image:e.target.value});
    if($('#shotReferenceUpload'))$('#shotReferenceUpload').onchange=e=>uploadFile('reference',e.target.files[0],s.id);
    if($('#shotReferenceAudioUpload'))$('#shotReferenceAudioUpload').onchange=e=>uploadFile('reference_audio',e.target.files[0],s.id);
    if($('#resolveVisual'))$('#resolveVisual').onclick=()=>guarded(()=>doRequest(`/shots/${s.id}/resolve`,{}));
    if($('#shotKeywords'))$('#shotKeywords').onchange=e=>patchShot({keywords:e.target.value.split('\n').map(x=>x.trim()).filter(Boolean)});
    const search=()=>guarded(()=>doRequest(`/shots/${s.id}/search`,{}));if($('#searchShot'))$('#searchShot').onclick=search;if($('#refreshCandidates'))$('#refreshCandidates').onclick=search;if($('#searchShotAdvanced'))$('#searchShotAdvanced').onclick=search;
    if($('#localBroll'))$('#localBroll').onchange=e=>uploadFile('broll',e.target.files[0],s.id);if($('#mediaStart'))$('#mediaStart').onchange=e=>patchShot({media_start:Number(e.target.value)});
    $$('[data-candidate]').forEach(b=>b.onclick=()=>guarded(()=>doRequest(`/shots/${s.id}/select`,{candidate_id:b.dataset.candidate})));
  }else{
    const saveConfig=changes=>patchShot({aroll_config:{provider:s.aroll_config?.provider||'global',resolution:s.aroll_config?.resolution||'',batch_size:s.aroll_config?.batch_size||0,positive_prompt:s.aroll_config?.positive_prompt||'',negative_prompt:s.aroll_config?.negative_prompt||'',...changes}});
    $('#shotArollProvider').onchange=e=>saveConfig({provider:e.target.value});if($('#shotArollResolution'))$('#shotArollResolution').onchange=e=>saveConfig({resolution:e.target.value});if($('#shotArollBatch'))$('#shotArollBatch').onchange=e=>saveConfig({batch_size:Number(e.target.value)||0});if($('#shotInfinitePositivePrompt'))$('#shotInfinitePositivePrompt').onchange=e=>saveConfig({positive_prompt:e.target.value});if($('#shotInfiniteNegativePrompt'))$('#shotInfiniteNegativePrompt').onchange=e=>saveConfig({negative_prompt:e.target.value});
    if($('#generateShotAroll')){$('#generateShotAroll').onclick=()=>startJob('aroll',s.id);$('#generateShotAroll').disabled=!state.arollSupported;}
  }
  if(state.busy)$$('#shotPanel button,#shotPanel input,#shotPanel textarea,#shotPanel select').forEach(e=>e.disabled=true);
}
async function patchShot(body){
  const projectId=pid(),shotId=state.selected;
  const save=state.saving.then(()=>api(`/projects/${projectId}/shots/${shotId}`,{method:'PATCH',body:JSON.stringify(body)}));
  state.saving=save.catch(()=>{});
  await guarded(async()=>{const updated=await save;if(state.project.id!==projectId)return;
    state.project=await api('/projects/'+projectId);
    if(document.activeElement?.matches('#shotPanel input,#shotPanel textarea')){renderTimeline();renderShots();renderPipeline();renderExports();syncPreview()}
    else await reload();
  });
}
function renderExports(){
  const p=state.project;$('#exportsPanel').innerHTML='<h3 class="detail-title">成片与交付文件</h3><p class="help">占位审片版和完整成片分开保留；修改镜头不会覆盖历史文件。</p>'+(p.exports.length?p.exports.slice().reverse().map(e=>{const draft=(e.kind||'final')==='draft',folder=e.file.slice(0,e.file.lastIndexOf('/')+1);return `<div class="export-card"><strong>${draft?'第一步 · 占位审片版':'完整成片'} <span class="phase-pill">${e.revision===p.revision?'当前版本':'历史版本'}</span>${e.auto_edit?'<span class="phase-pill edit">自动精剪</span>':''}</strong><p>${new Date(e.created_at*1000).toLocaleString('zh-CN')} · ${esc(e.size)} · ${fmt(e.duration)}</p>${e.auto_edit?`<p class="help">原片 ${fmt(e.source_duration)} · 剪掉 ${Number(e.removed_seconds||0).toFixed(1)} 秒${e.bgm?' · 已混入自动压低的背景音乐':''}</p>`:''}${e.aroll_placeholders?`<p class="help">${e.aroll_placeholders} 段 A-roll 使用参考图占位</p>`:''}${e.fallbacks?`<p class="export-warning">${e.fallbacks} 段 B-roll 使用人物图占位</p>`:''}${e.looped?`<p class="help">${e.looped} 段素材循环播放</p>`:''}<a href="${media(e.file)}" target="_blank" class="button">${draft?'播放审片版':'播放成片'} ↗</a> <a href="${media(e.file)}" download="${esc(p.name)}-${draft?'审片版':'完整成片'}.mp4" class="button">下载 MP4</a><p><a class="source-link" href="${media(folder+'subtitles.srt')}" download>字幕 SRT</a> · <a class="source-link" href="${media(folder+'manifest.json')}" download>镜头与来源清单</a>${e.auto_edit?` · <a class="source-link" href="${media(folder+'edit-plan.json')}" download>精剪计划 JSON</a>`:''}</p></div>`}).join(''):'<div class="panel-empty">还没有导出文件。<br>两步精修模式会先生成参考图占位审片版。</div>');
}
function renderEditPlan(){
  const p=state.project,box=$('#editPlanSummary'),plan=p?.edit_plan;
  $('#bgmToggle').disabled=!p?.bgm||state.busy;$('#bgmVolume').disabled=!p?.bgm||state.busy;
  if(!p?.shots?.length){box.textContent='生成分镜后，可先查看会剪掉多少停顿，再决定是否用于导出。';box.className='edit-plan-summary';return}
  if(!plan){box.textContent='还没有精剪计划。点击上方按钮后，只会分析并预览，不会改动原时间线。';box.className='edit-plan-summary';return}
  const stale=!p.edit_plan_current;
  box.className='edit-plan-summary'+(stale?' stale':' ready');
  box.innerHTML=stale?'镜头或参数已改变，导出时会自动刷新计划。':`预计成片 <strong>${fmt(plan.output_duration)}</strong> · 剪掉 <strong>${Number(plan.removed_seconds||0).toFixed(1)} 秒</strong> · ${plan.remove_ranges?.length||0} 处长停顿 · ${plan.overlays?.length||0} 张信息卡片`;
}
function shotAt(time){
  const shots=state.project?.shots||[];if(!shots.length)return null;const t=Math.max(0,Math.min(Number(time)||0,state.project.duration));let i=Math.max(0,Math.min(state.activeShotIndex||0,shots.length-1));
  if(t>=shots[i].start&&(t<shots[i].end||i===shots.length-1)){state.activeShotIndex=i;return shots[i]}
  let lo=0,hi=shots.length-1;while(lo<=hi){const mid=(lo+hi)>>1,s=shots[mid];if(t<s.start)hi=mid-1;else if(t>=s.end&&mid<shots.length-1)lo=mid+1;else{state.activeShotIndex=mid;return s}}
  state.activeShotIndex=shots.length-1;return shots.at(-1)
}
function updateTimelinePosition(time,shot){
  const canvas=$('#timelineCanvas'),playhead=$('#timelinePlayhead'),duration=Math.max(.001,state.project?.duration||0);if(canvas&&playhead){const x=54+Math.max(0,Math.min(1,time/duration))*Math.max(1,canvas.clientWidth-54);playhead.style.transform=`translate3d(${x}px,0,0)`}
  if(shot?.id!==state.activeShotId){state.activeShotId=shot?.id||null;$$('[data-seek],[data-shot]').forEach(el=>el.classList.toggle('playing',el.dataset.seek===state.activeShotId||el.dataset.shot===state.activeShotId));if(!$('#audioPlayer').paused)ensureTimeVisible(time)}
}
function seek(t){const audio=$('#audioPlayer');if(!state.project?.audio)return;audio.currentTime=Math.min(Math.max(0,t),state.project.duration);syncPreview(true)}
function syncPreview(force=false){
  const p=state.project;if(!p)return;const audio=$('#audioPlayer'),video=$('#brollPreview'),t=audio.currentTime||0;
  const timeLabel=fmtPrecise(t);if(timeLabel!==state.lastTimeLabel){state.lastTimeLabel=timeLabel;$('#currentTime').textContent=timeLabel}$('#scrubber').value=t;$('#playButton').textContent=audio.paused?'▶':'Ⅱ';
  const shot=shotAt(t),role=shot?roleOf(shot):null;updateTimelinePosition(t,shot);const hasB=role&&role!=='A'&&shot.asset,hasA=role==='A'&&shot.aroll_ready,sourceVideo=!hasA&&!hasB&&role!=='A'&&role!=='M'&&hostIsVideo(),visual=hasA?shot.aroll_asset:hasB?shot.asset:sourceVideo?p.host_media_asset:null;
  const isVideo=visual&&/\.(mp4|webm|mov|mkv|m4v)$/i.test(visual),key=visual?(hasA?'aroll|'+visual:(shot?.id||'source')+'|'+visual+'|'+(shot?.media_start||0)):'host|'+host();
  const kindLabel=role==='A'?(hasA?'A 人物 · '+arollName():sourceVideo?'A 人物 · 原循环视频 · 待生成口型':'A 人物 · 待生成口型'):role?`${role} · ${roleName(role).split(' ')[1]||roleName(role)}${hasB?'':' · 人物图 / 模板底图'}`:'待生成';if(kindLabel!==state.lastKindLabel){state.lastKindLabel=kindLabel;$('#currentKind').textContent=kindLabel}
  const scale=role==='A'?(shot.camera==='close'?1.40:shot.camera==='medium_close'?1.22:1):1;
  video.style.transform=`scale(${scale})`;$('#hostPreview').style.transform=`scale(${scale})`;
  if(state.previewKey!==key){
    state.previewKey=key;video.pause();video.classList.toggle('hidden',!isVideo);$('#hostPreview').classList.toggle('hidden',!!isVideo);
    if(isVideo){video.src=media(visual);video.load();video.onloadedmetadata=()=>syncPreview(true);video.onerror=()=>toast('该素材暂时无法预览，请换一个候选或导入其他素材')}
    else{$('#hostPreview').src=visual?media(visual):host();video.removeAttribute('src');video.load()}
  }
  if(isVideo&&video.readyState>=1&&Number.isFinite(video.duration)){
    const offset=hasA?(shot.aroll_media_start||0):sourceVideo?0:shot.media_start||0,elapsed=sourceVideo?t:Math.max(0,t-shot.start),duration=video.duration;
    const desired=hasA?Math.min(offset+elapsed,Math.max(0,duration-.025)):(offset+elapsed)%duration;
    if(force||Math.abs(video.currentTime-desired)>.25)video.currentTime=desired;
    video.loop=!hasA;if(!audio.paused&&video.paused)video.play().catch(()=>{});if(audio.paused&&!video.paused)video.pause();
  }
  const caption=p.options.subtitles?(p.captions||[]).find(s=>t>=s.start&&t<s.end):null,captionText=caption?.text||'';if(captionText!==state.lastCaption){state.lastCaption=captionText;$('#previewCaption').textContent=captionText}
}
function startPreviewAnimation(){
  if(previewAnimation)return;
  const tick=()=>{syncPreview();if($('#audioPlayer').paused){previewAnimation=0;return}previewAnimation=requestAnimationFrame(tick)};
  previewAnimation=requestAnimationFrame(tick);
}
async function doRequest(suffix,body){
  await state.saving;
  state.pending++;renderStatus();
  try{await api('/projects/'+pid()+suffix,{method:'POST',body:JSON.stringify(body)});await reload()}
  finally{state.pending--;renderStatus()}
}
async function confirmReplace(message){
  const d=$('#confirmDialog');$('#confirmMessage').textContent=message;d.showModal();
  return new Promise(resolve=>{const finish=v=>{d.close();resolve(v)};$('#confirmYes').onclick=()=>finish(true);$('#confirmNo').onclick=()=>finish(false);d.querySelector('.close-dialog').onclick=()=>finish(false);d.oncancel=()=>resolve(false)})
}
async function confirmProjectDeletion(){
  const d=$('#deleteProjectDialog');
  $('#deleteProjectMessage').textContent=`「${state.project.name}」删除后将不再出现在项目列表中。`;
  d.showModal();
  return new Promise(resolve=>{
    const finish=value=>{d.close();resolve(value)};
    $('#deleteProjectConfirm').onclick=()=>finish(true);
    $('#deleteProjectCancel').onclick=()=>finish(false);
    d.querySelector('.close-dialog').onclick=()=>finish(false);
    d.oncancel=event=>{event.preventDefault();finish(false)};
  });
}
async function editShotStructure(action,body){
  const projectId=pid(),shotId=state.selected;state.pending++;renderStatus();
  try{await state.saving;const result=await api(`/projects/${projectId}/shots/${shotId}/${action}`,{method:'POST',body:JSON.stringify(body)});if(state.project.id!==projectId)return;state.selected=result.selected_id||shotId;state.project=await api('/projects/'+projectId);state.activeShotIndex=0;state.activeShotId=null;renderAll();const selected=state.project.shots.find(s=>s.id===state.selected);if(selected){seek(selected.start);ensureTimeVisible(selected.start)}toast(action==='split'?`已吸附到 ${fmt(result.split_time)} 的语义边界并拆分`:'已合并连续语义镜头')}
  catch(error){toast(error.message)}finally{state.pending--;renderStatus()}
}
async function deleteCurrentProject(){
  if(!state.project||!await confirmProjectDeletion())return;
  const project=state.project;
  await state.saving;
  state.pending++;renderStatus();
  let result;
  try{
    for(const mediaElement of [$('#audioPlayer'),$('#brollPreview'),$('#portraitVideo')]){mediaElement.pause();mediaElement.removeAttribute('src');mediaElement.load()}
    result=await api('/projects/'+project.id,{method:'DELETE'});
  }catch(error){renderAll();throw error}
  finally{state.pending--;renderStatus()}
  localStorage.removeItem('solo-project');localStorage.removeItem('solo-script-'+project.id);localStorage.removeItem('solo-input-'+project.id);
  state.project=null;state.selected=null;state.previewKey='';
  await refreshProjects();
  let next=state.projects[0];
  if(!next){next=await api('/projects',{method:'POST',body:JSON.stringify({name:'我的第一期单人播客'})});await refreshProjects()}
  await openProject(next.id);
  toast(`已删除「${result.name}」，并保留在本机回收目录`);
}
function morningSourceLink(source,label){return source&&safeURL(source.source_url)?`<a href="${esc(source.source_url)}" target="_blank" rel="noopener noreferrer">${esc(label)}：${esc(source.source_name)} ↗</a>`:''}
function renderMorning(){
  const data=state.morning,stories=$('#morningStories'),confirm=$('#morningConfirmArea'),preview=$('#morningScriptPreview');
  $('#morningConfirmCheck').checked=false;$('#confirmMorning').disabled=true;
  if(!data?.ready){$('#morningStatus').textContent=data?.message||'今天还没有可用晨报';stories.innerHTML='<div class="morning-empty">点击“生成今日晨报”，完成搜集、筛选和写稿。</div>';confirm.classList.add('hidden');preview.classList.add('hidden');return}
  $('#morningStatus').textContent=`${data.date} · ${data.stories.length} 条 · ${data.script_chars} 字`;
  stories.innerHTML=data.stories.map((story,index)=>`<article class="morning-story"><div class="morning-story-head"><span class="morning-story-number">${String(index+1).padStart(2,'0')}</span><div><h3>${esc(story.title)}</h3><p>${esc(story.summary)}</p></div></div><p class="morning-impact"><strong>商业意义：</strong>${esc(story.business_impact)}</p><div class="morning-sources">${morningSourceLink(story.primary_source,'一手来源')}${morningSourceLink(story.media_source,'媒体来源')}${!story.primary_source&&!story.media_source?morningSourceLink(story.source,'来源'):''}</div></article>`).join('');
  $('#morningScriptText').textContent=data.script;$('#morningScriptCount').textContent=`${data.script_chars} 字`;preview.classList.remove('hidden');confirm.classList.remove('hidden');
}
async function loadMorning(){state.morning=await api('/morning-briefing');renderMorning()}
async function openMorning(){const dialog=$('#morningBriefingDialog');dialog.showModal();await guarded(loadMorning)}
async function generateMorning(){
  const dialog=$('#morningBriefingDialog');dialog.classList.add('morning-loading');$('#morningStatus').textContent='正在搜集并核查过去 24 小时信息，通常需要半分钟…';
  try{state.morning=await api('/morning-briefing/generate',{method:'POST',body:'{}'});renderMorning();toast(`今日晨报已生成：${state.morning.stories.length} 条`)}
  finally{dialog.classList.remove('morning-loading')}
}
async function confirmMorning(){
  if(!state.morning?.ready||!$('#morningConfirmCheck').checked)return;
  const result=await api('/morning-briefing/confirm',{method:'POST',body:JSON.stringify({generation_id:state.morning.generation_id})});
  $('#morningBriefingDialog').close();await refreshProjects();await openProject(result.project_id);localStorage.setItem('solo-input-'+result.project_id,'text');setInputMode('text');toast(result.reused?'这份晨报已经在 Scene Flow 中，已为你打开':'晨报已送入 Scene Flow；确认人物与声音后即可生成视频');
}
function showPreflight(check){
  const dialog=$('#preflightDialog');$('#preflightIssues').innerHTML=check.issues.map(issue=>`<p><strong>${esc(issue.message)}</strong></p>`).join('');
  $('#preflightInstall').classList.toggle('hidden',!check.issues.some(issue=>issue.action==='install'));dialog.showModal();
}
async function startJob(action,shotId=null){
  try{await flushScript()}catch(e){toast(e.message);return}
  await state.saving;
  await checkService();renderStatus();
  if(!state.arollSupported){toast('请先运行「重启工作台.bat」载入更新，再继续生成。');return}
  if(['all','draft','finish'].includes(action)){
    const check=await guarded(()=>api('/projects/'+pid()+'/preflight?action='+action));if(!check)return;
    state.preflight=check;renderStatus();if(!check.ok){showPreflight(check);return}
  }
  if((action==='transcribe'&&state.project.segments.length)||(action==='plan'&&state.project.shots.length)){
    if(!await confirmReplace(action==='transcribe'?'重新转录会重建本期字幕，并清除当前分镜。已导出的成片和原始素材会保留。':'重新分镜会替换当前镜头编辑和素材选择。已导出的成片和素材文件会保留。'))return;
  }
  state.startingAction=action;renderStatus();
  try{await guarded(async()=>{await api(`/projects/${pid()}/jobs`,{method:'POST',body:JSON.stringify({action,shot_id:shotId})});await reload();if(['render','all','draft','finish'].includes(action))setPanel('exports')})}
  finally{if(state.startingAction===action)state.startingAction=null;renderStatus()}
}
async function uploadFile(kind,file,shotId=''){
  await state.saving.catch(()=>{});
  if(!file)return;
  if(kind==='audio'&&state.project.audio){if(!await confirmReplace('换入音频会清除本期字幕和分镜，重新建立时间轴。历史成片仍会保留。'))return}
  if(kind==='srt'&&state.project.shots.length){if(!await confirmReplace('导入字幕会清除当前分镜，需要重新进行语义分镜。历史成片会保留。'))return}
  await guarded(async()=>{
    const data=new FormData();data.append('kind',kind);data.append('file',file);if(shotId)data.append('shot_id',shotId);
    state.pending++;renderStatus();toast('正在导入 '+file.name+'…');
    try{await api('/projects/'+pid()+'/upload',{method:'POST',body:data});if(kind==='audio'){localStorage.removeItem('solo-script-'+pid());localStorage.setItem('solo-input-'+pid(),'audio')}await reload();if(kind==='audio'){$('#audioPlayer').src=media(state.project.audio);seek(0)}if(kind==='voice_reference'){rememberScript();await flushScript()}toast(kind==='voice_reference'?'参考声音已更新':'导入完成')}
    finally{state.pending--;renderStatus()}
  });
}
async function patchOptions(values){await guarded(async()=>{await api('/projects/'+pid(),{method:'PATCH',body:JSON.stringify({options:values})});await reload();if(values.aspect_ratio)toast(`已切换到 ${values.aspect_ratio}；自动 B-roll 将按新画幅重新匹配`)})}
async function poll(){
  if(state.polling||!state.project)return;state.polling=true;
  try{
    if(!state.lastHealth||Date.now()-state.lastHealth>15000){await checkService();state.lastHealth=Date.now();renderStatus()}
    const p=await api('/projects/'+pid()),old=state.project,changed=JSON.stringify(p.job)!==JSON.stringify(old.job);
    if(Date.now()-state.lastProjectRefresh>3500){state.lastProjectRefresh=Date.now();await refreshProjects()}
    if(state.project.id!==p.id)return;
    if(changed){
      if(p.job?.status==='running'){state.project.job=p.job;renderStatus();renderPipeline()}
      else if(document.activeElement?.matches('input,textarea,select')&&!state.busy){/* Do not replace an active editor. */}
      else{state.project=p;if(old.job?.action==='setup_models')await loadProviderState();renderAll();await refreshPreflight();await refreshProjects();if(old.job?.status==='running')toast(p.job.message)}
    }
  }catch(e){/* Keep current project visible during a temporary reconnect. */}finally{state.polling=false}
}
$('#newProject').onclick=()=>{$('#newDialog').showModal();$('#newForm input').focus()};
$('#morningBriefingButton').onclick=()=>guarded(openMorning);$('#generateMorning').onclick=()=>guarded(generateMorning);$('#refreshMorning').onclick=()=>guarded(loadMorning);$('#morningConfirmCheck').onchange=e=>{$('#confirmMorning').disabled=!e.target.checked};$('#confirmMorning').onclick=()=>guarded(confirmMorning);
$$('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('#newForm').onsubmit=e=>{e.preventDefault();guarded(async()=>{const p=await api('/projects',{method:'POST',body:JSON.stringify({name:new FormData(e.target).get('name')})});$('#newDialog').close();e.target.reset();await refreshProjects();await openProject(p.id)})};
$('#projectName').onchange=e=>guarded(async()=>{await api('/projects/'+pid(),{method:'PATCH',body:JSON.stringify({name:e.target.value})});state.project.name=e.target.value;$('#crumbTitle').textContent=e.target.value;await refreshProjects()});
$('#deleteProjectButton').onclick=()=>guarded(deleteCurrentProject);
$('#audioUpload').onchange=e=>uploadFile('audio',e.target.files[0]);$('#portraitUpload').onchange=e=>uploadFile('portrait',e.target.files[0]);$('#srtUpload').onchange=e=>uploadFile('srt',e.target.files[0]);$('#bgmUpload').onchange=e=>uploadFile('bgm',e.target.files[0]);
$('#hostMaterial').onchange=()=>renderStatus();
$('#useHostMaterial').onclick=()=>guarded(async()=>{
  await state.saving;state.pending++;renderStatus();toast('正在导入人物素材…');
  try{await api('/projects/'+pid()+'/host-material',{method:'POST',body:JSON.stringify({name:$('#hostMaterial').value})});await reload();toast('人物素材已更新，可生成 A-roll 口型')}
  finally{state.pending--;renderStatus()}
});
api('/host-materials').then(items=>{$('#hostMaterial').innerHTML='<option value="">选择人物图片或循环视频…</option>'+items.map(x=>`<option value="${esc(x.name)}">${esc(x.label||x.name)}</option>`).join('')}).catch(()=>{});
const drop=$('#audioDrop');drop.ondragover=e=>{e.preventDefault();drop.classList.add('dragover')};drop.ondragleave=()=>drop.classList.remove('dragover');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('dragover');if(!state.busy)uploadFile('audio',e.dataTransfer.files[0])};
$('#aspectRatio').onchange=e=>patchOptions({aspect_ratio:e.target.value});$('#resolution').onchange=e=>patchOptions({resolution:e.target.value});$('#subtitlesToggle').onchange=e=>patchOptions({subtitles:e.target.checked});
$('#autoEditToggle').onchange=e=>patchOptions({auto_edit_enabled:e.target.checked});$('#removePausesToggle').onchange=e=>patchOptions({auto_edit_remove_pauses:e.target.checked});$('#pauseThreshold').onchange=e=>patchOptions({auto_edit_pause_threshold:Number(e.target.value)});$('#highlightToggle').onchange=e=>patchOptions({auto_edit_highlights:e.target.checked});$('#cardsToggle').onchange=e=>patchOptions({auto_edit_cards:e.target.checked});$('#bgmToggle').onchange=e=>patchOptions({bgm_enabled:e.target.checked});$('#bgmVolume').onchange=e=>patchOptions({bgm_volume:Number(e.target.value)});
$('#transcribeButton').onclick=()=>startJob('transcribe');$('#planButton').onclick=()=>startJob('plan');$('#materialsButton').onclick=()=>startJob('materials');$('#autoButton').onclick=()=>startJob(primaryAction());$('#storyboardPreviewButton').onclick=()=>startJob('draft');$('#exportButton').onclick=()=>startJob(hasReviewCut()?'finish':'render');
$('#generateEditPlan').onclick=()=>guarded(async()=>{await state.saving;state.pending++;renderStatus();try{const plan=await api('/projects/'+pid()+'/edit-plan',{method:'POST',body:'{}'});await reload();toast(`精剪计划已生成：预计剪掉 ${Number(plan.removed_seconds||0).toFixed(1)} 秒`)}finally{state.pending--;renderStatus()}});
$('#cancelJob').onclick=()=>guarded(async()=>{const r=await api('/projects/'+pid()+'/cancel',{method:'POST',body:'{}'});toast(r.message)});
$('#resumeJob').onclick=()=>{const j=state.project.job;startJob(['all','draft','finish','tts','setup_models','transcribe','plan','materials','aroll','render'].includes(j?.action)?j.action:primaryAction(),j?.shot_id||null)};
$$('[data-filter]').forEach(b=>b.onclick=()=>{state.filter=b.dataset.filter;$$('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));renderShots()});
$$('[data-panel]').forEach(b=>b.onclick=()=>setPanel(b.dataset.panel));
$('#playButton').onclick=()=>guarded(async()=>{const a=$('#audioPlayer');if(a.paused)await a.play();else a.pause();syncPreview()});
$('#playVoice').onclick=()=>guarded(async()=>{const a=$('#audioPlayer');if(a.paused)await a.play();else a.pause();syncPreview()});
$('#muteButton').onclick=()=>{const a=$('#audioPlayer');a.muted=!a.muted;$('#muteButton').textContent=a.muted?'×':'♪'};
$('#scrubber').oninput=e=>{timelineSeekValue=Number(e.target.value);if(!timelineSeekAnimation)timelineSeekAnimation=requestAnimationFrame(()=>{timelineSeekAnimation=0;seek(timelineSeekValue)})};
['timeupdate','play','pause','ended','seeked'].forEach(event=>$('#audioPlayer').addEventListener(event,()=>{syncPreview(event==='seeked');$('#playVoice').textContent=event==='play'?'❚❚ 暂停配音':'▶ 试听配音';if(event==='play')startPreviewAnimation()}));
document.addEventListener('keydown',e=>{if(e.target.matches('input,textarea,select,button')||document.querySelector('dialog[open]')||!state.project?.audio)return;if(e.code==='Space'){e.preventDefault();$('#playButton').click()}else if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const step=e.shiftKey?1:.1;seek($('#audioPlayer').currentTime+(e.key==='ArrowRight'?step:-step))}});
let timelineResizeTimer=0;window.addEventListener('resize',()=>{if(!state.project||state.timelineZoom)return;clearTimeout(timelineResizeTimer);timelineResizeTimer=setTimeout(renderTimeline,120)});
function fillProviderSelect(select,items){
  const current=select.value;select.innerHTML=items.map(item=>`<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('');
  if(items.some(item=>item.id===current))select.value=current;
}
function populateProviderOptions(){
  if(!state.providerCatalog)return;
  fillProviderSelect($('#llmProvider'),state.providerCatalog.llm);fillProviderSelect($('#brollProvider'),state.providerCatalog.broll);
  fillProviderSelect($('#arollProvider'),state.providerCatalog.aroll);fillProviderSelect($('#arollCustomType'),state.providerCatalog.aroll_custom_types);
}
function selectedMetadata(kind,id){return state.providerCatalog?.[kind]?.find(item=>item.id===id)||{name:id}}
function h3ConfiguredInForm(){const field=$('#settingsForm')?.elements?.aroll_autodl_api_key;return !!(field?.value||state.settingsData?.aroll_autodl_api_key_configured)}
function syncProviderFields(){
  const form=$('#settingsForm'),llm=form.elements.llm_provider.value,broll=form.elements.broll_provider.value,aroll=form.elements.aroll_provider.value,custom=form.elements.aroll_custom_type.value;
  $('#llmCustomFields').classList.toggle('hidden',llm!=='custom');
  const llmMeta=selectedMetadata('llm',llm);$('#llmKeyLink').textContent=llm==='deepseek'?'获取 DeepSeek API Key ↗':'API Key 由您的服务商提供';$('#llmKeyLink').href=llmMeta.key_url||'#';$('#llmKeyLink').classList.toggle('disabled-link',!llmMeta.key_url);
  $$('[data-broll-key]').forEach(group=>group.classList.toggle('hidden',group.dataset.brollKey!==broll));
  const brollMeta=selectedMetadata('broll',broll);$('#brollKeyLink').textContent=`获取 ${brollMeta.name} API Key ↗`;$('#brollKeyLink').href=brollMeta.key_url||'#';
  $('#latentsyncFields').classList.toggle('hidden',aroll!=='latentsync');$('#musetalkFields').classList.toggle('hidden',aroll!=='musetalk');$('#wav2lipFields').classList.toggle('hidden',aroll!=='wav2lip');$('#autodlH3Fields').classList.toggle('hidden',aroll!=='autodl_h3');$('#customArollFields').classList.toggle('hidden',!['custom','infinitetalk'].includes(aroll));
  const infinitePromptSupported=state.settingsData?.aroll_infinitetalk_prompt_supported===true;
  $('#infinitetalkHelp').classList.toggle('hidden',aroll!=='infinitetalk');$('#infinitetalkPromptFields').classList.toggle('hidden',aroll!=='infinitetalk'||!infinitePromptSupported);
  $('#infinitetalkHelp').textContent=infinitePromptSupported?'当前工作流已识别正向和负向提示词输入；修改时不会改写原工作流文件。':'当前工作流没有识别到可安全映射的正向、负向提示词输入。';
  $('#arollCustomType').closest('label').classList.toggle('hidden',aroll==='infinitetalk');
  $('#comfyuiFields').classList.toggle('hidden',aroll!=='infinitetalk'&&custom!=='comfyui');$('#externalArollFields').classList.toggle('hidden',aroll==='infinitetalk'||custom!=='external_api');
  $('#autodlH3StatusText').textContent=h3ConfiguredInForm()?'✓ Token 已保存在本机':'○ 尚未配置 Token';
}
function renderSettingsStatus(){
  const s=state.providerStatus;if(!s)return;
  $('#connectionStatus').textContent=`分镜 AI：${s.llm.name}${s.llm.configured?'已配置':'待配置'} · B-roll：${s.broll.name}${s.broll.configured?'已配置':'待配置'} · A-roll：${s.aroll.name}${s.aroll.ready?'已就绪':'待准备'}`;
  $('#llmState').textContent=s.llm.configured?'✓ 已配置':'○ 尚未配置';$('#brollState').textContent=s.broll.configured?'✓ 已配置':'○ 尚未配置';$('#arollState').textContent=s.aroll.ready?'✓ 已就绪':'○ 尚未准备';
  $('#arollStatusText').textContent=(s.aroll.id==='musetalk'?(s.aroll.ready?'✓ ':'○ '):'')+(s.aroll.message||'');
  $('#latentsyncStatusText').textContent=s.aroll.id==='latentsync'?((s.aroll.ready?'✓ ':'○ ')+(s.aroll.message||'尚未连接')):'○ 选择后测试本机 8189';
  $('#wav2lipStatusText').textContent=s.aroll.id==='wav2lip'?((s.aroll.ready?'✓ ':'○ ')+(s.aroll.message||'尚未安装')):'○ 尚未安装';
  $('#autodlH3StatusText').textContent=s.aroll.id==='autodl_h3'?((s.aroll.ready?'✓ ':'○ ')+(s.aroll.message||'尚未配置')):(h3ConfiguredInForm()?'✓ Token 已保存在本机':'○ 尚未配置 Token');
}
function settingsFormBody(){return Object.fromEntries(new FormData($('#settingsForm')))}
async function testProvider(kind){
  const output=$('#'+kind+'TestStatus');output.textContent='正在测试…';
  try{const result=await api('/settings/test',{method:'POST',body:JSON.stringify({...settingsFormBody(),type:kind})});output.textContent='✓ '+result.message}
  catch(error){output.textContent='! '+error.message}
}
$$('#settingsForm select[id$="Provider"],#arollCustomType').forEach(select=>select.onchange=syncProviderFields);
$$('[data-test-provider]').forEach(button=>button.onclick=()=>testProvider(button.dataset.testProvider));
$('#arollWorkflowUpload').onchange=e=>guarded(async()=>{
  const file=e.target.files[0];if(!file)return;const data=new FormData();data.append('file',file);$('#workflowStatus').textContent='正在校验工作流…';
  const s=await api('/settings/aroll-workflow',{method:'POST',body:data});state.settingsData=s;$('#settingsForm').elements.aroll_comfyui_workflow.value=s.aroll_comfyui_workflow;$('#settingsForm').elements.aroll_comfyui_workflow_hash.value=s.aroll_comfyui_workflow_hash;$('#workflowStatus').textContent='✓ workflow_api.json 已导入';
});
async function openGlobalApiSettings(){
  await loadProviderState();const s=state.settingsData,form=$('#settingsForm');populateProviderOptions();
  for(const key of ['llm_provider','llm_custom_name','llm_custom_base_url','llm_custom_model','broll_provider','aroll_provider','aroll_custom_type','aroll_musetalk_quality','aroll_musetalk_parsing_mode','aroll_musetalk_extra_margin','aroll_musetalk_left_cheek_width','aroll_musetalk_right_cheek_width','aroll_musetalk_audio_padding_left','aroll_musetalk_audio_padding_right','aroll_latentsync_url','aroll_latentsync_lips_expression','aroll_latentsync_inference_steps','aroll_comfyui_url','aroll_comfyui_workflow','aroll_comfyui_workflow_hash','aroll_person_node','aroll_audio_node','aroll_output_node','aroll_external_name','aroll_external_url','aroll_external_model','aroll_autodl_resolution','aroll_autodl_cut_style','aroll_infinitetalk_positive_prompt','aroll_infinitetalk_negative_prompt','tts_index_url','asr_model','asr_device','aroll_batch_size'])if(form.elements[key])form.elements[key].value=s[key]??'';
  if(state.project?.aroll_provider?.id)form.elements.aroll_provider.value=state.project.aroll_provider.id;
  for(const key of ['llm_api_key','pexels_api_key','pixabay_api_key','aroll_external_api_key','aroll_autodl_api_key','tts_seed_api_key']){form.elements[key].value='';form.elements[key].placeholder=s[key+'_configured']?'••••••••••••':'尚未配置'}
  $('#workflowStatus').textContent=s.aroll_comfyui_workflow_hash?'✓ workflow_api.json 已导入':'导入 workflow_api.json';
  syncProviderFields();renderSettingsStatus();$('#settingsDialog').showModal();
}
$('#globalApiButton').onclick=()=>guarded(openGlobalApiSettings);
$('#settingsButton').onclick=()=>guarded(openGlobalApiSettings);
$$('[data-open-settings]').forEach(button=>button.onclick=()=>guarded(openGlobalApiSettings));
function globalSettingsChanged(body){
  return Object.entries(body).some(([key,value])=>{
    if(key==='aroll_provider'||(key.endsWith('api_key')&&!value))return false;
    return String(value??'')!==String(state.settingsData?.[key]??'');
  });
}
$('#settingsForm').onsubmit=e=>{e.preventDefault();guarded(async()=>{
  const body=settingsFormBody(),projectProvider=body.aroll_provider;
  if(globalSettingsChanged(body)){
    const globalBody={...body,aroll_provider:state.settingsData.aroll_provider};
    state.settingsData=await api('/settings',{method:'PUT',body:JSON.stringify(globalBody)});applyAsrSettings(state.settingsData);
  }
  if(state.project&&projectProvider!==state.project.aroll_provider?.id){
    await api('/projects/'+pid(),{method:'PATCH',body:JSON.stringify({aroll_provider_id:projectProvider})});
    state.project=await api('/projects/'+pid());
  }
  await loadProviderState();renderAll();await refreshPreflight();$('#settingsDialog').close();toast('本项目的人物口型方案已保存')
})};
function applyAsrSettings(s){
  state.asrModel=['large-v3','small','base'].includes(s?.asr_model)?s.asr_model:'base';
  const advanced=$('#settingsForm').elements.asr_model;if(advanced)advanced.value=state.asrModel;
}
function readDraft(id){try{return JSON.parse(localStorage.getItem('solo-script-'+id)||'null')}catch{return null}}
function scriptValue(){return {text:$('#scriptText').value,provider:$('#ttsProvider').value,speaker:$('#ttsSpeaker').value,language:$('#ttsLanguage').value,speed:Number($('#ttsSpeed').value),reference:state.project?.voice_reference||''}}
function rememberScript(){if(state.project)localStorage.setItem('solo-script-'+pid(),JSON.stringify(scriptValue()))}
function setInputMode(mode){
  state.inputMode=mode;
  $$('[data-input]').forEach(b=>{const active=b.dataset.input===mode;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active))});
  $('#textInputPanel').classList.toggle('hidden',mode!=='text');$('#audioInputPanel').classList.toggle('hidden',mode!=='audio');
  const textMode=mode==='text';
  $('#previewStartKicker').textContent=textMode?'01 — YOUR WORDS, YOUR STORY':'01 — YOUR VOICE, YOUR STORY';
  $('#previewStartTitle').textContent=textMode?'从一段文字开始。':'从一个声音开始。';
  $('#previewStartHelp').textContent=textMode?'输入文稿并选择声音，让每段表达都有合适的画面。':'导入一段音频，让每段表达都有合适的画面。';
}
function flushScript(){
  if(!state.project||state.busy)return state.saving;
  const id=pid(),value=readDraft(id);
  if(!value)return state.saving;
  if(!value.text.trim()){if(state.project.script)throw Error('原稿为空，请输入文字，或导入音频后继续');return state.saving}
  if(JSON.stringify(value)===JSON.stringify(state.project.script))return state.saving;
  const previous=state.saving.catch(()=>{});
  state.saving=previous.then(async()=>{
    const p=await api('/projects/'+id+'/script',{method:'PUT',body:JSON.stringify(value)});
    if(state.project?.id===id){state.project.script=p.script;state.project.revision=p.revision}
    if(JSON.stringify(readDraft(id))===JSON.stringify(value))localStorage.removeItem('solo-script-'+id);
  });
  return state.saving;
}
$$('[data-input]').forEach(b=>b.onclick=()=>{localStorage.setItem('solo-input-'+pid(),b.dataset.input);setInputMode(b.dataset.input)});
$('#scriptText').oninput=()=>{rememberScript();renderStatus()};
$('#scriptText').onblur=()=>guarded(flushScript);
$('#ttsProvider').onchange=()=>{updateVoiceOptions();updateTtsNotice();rememberScript();guarded(flushScript)};
$('#ttsLanguage').onchange=()=>{updateVoiceOptions();rememberScript();guarded(flushScript)};
for(const id of ['#ttsSpeaker','#ttsSpeed'])$(id).onchange=()=>{rememberScript();guarded(flushScript)};
$('#voiceReferenceUpload').onchange=e=>{const file=e.target.files[0];if(file)uploadFile('voice_reference',file).then(()=>{e.target.value=''})};
$('#ttsButton').onclick=()=>guarded(()=>startJob('tts'));
function requestWav2LipLicense(){
  const dialog=$('#wav2lipLicenseDialog'),checkbox=$('#wav2lipLicenseAck'),proceed=$('#wav2lipLicenseContinue');
  checkbox.checked=false;proceed.disabled=true;dialog.showModal();
  return new Promise(resolve=>{
    const finish=value=>{dialog.close();resolve(value)};
    checkbox.onchange=()=>{proceed.disabled=!checkbox.checked};
    proceed.onclick=()=>finish(checkbox.checked);
    $('#wav2lipLicenseCancel').onclick=()=>finish(false);
    dialog.querySelector('.close-dialog').onclick=()=>finish(false);
    dialog.oncancel=()=>resolve(false);
  });
}
async function installSelectedAroll(){
  if($('#settingsDialog').open){
    state.settingsData=await api('/settings',{method:'PUT',body:JSON.stringify(settingsFormBody())});
    applyAsrSettings(state.settingsData);await loadProviderState();$('#settingsDialog').close();
  }
  if($('#preflightDialog').open)$('#preflightDialog').close();
  if(state.settingsData?.aroll_provider==='wav2lip'&&!state.settingsData.wav2lip_license_acknowledged_current){
    if(!await requestWav2LipLicense())return;
    state.settingsData=await api('/settings/wav2lip-license',{method:'POST',body:JSON.stringify({acknowledged:true})});
    await loadProviderState();
  }
  await startJob('setup_models');
}
$('#installAroll').onclick=()=>guarded(installSelectedAroll);$('#installWav2lip').onclick=()=>guarded(installSelectedAroll);
$('#wav2lipModelUpload').onchange=e=>guarded(async()=>{
  const file=e.target.files[0];if(!file)return;
  const output=$('#wav2lipModelStatus');output.textContent='正在校验官方模型文件…';
  const data=new FormData();data.append('file',file);
  const result=await api('/settings/wav2lip-model',{method:'POST',body:data});output.textContent='✓ '+result.message;
  e.target.value='';
});
$('#preflightBack').onclick=()=>$('#preflightDialog').close();
$('#preflightSettings').onclick=()=>guarded(async()=>{$('#preflightDialog').close();await openGlobalApiSettings()});
$('#preflightInstall').onclick=()=>guarded(installSelectedAroll);
async function refreshLocalModels(){
  const m=await api('/local-models');
  state.ttsStatus=m;
  updateTtsNotice();
}
refreshLocalModels().catch(()=>{});
async function checkService(){try{const h=await api('/health');state.arollSupported=h.features?.reliable_planning===true&&!h.update_required}catch{state.arollSupported=false}}
guarded(async()=>{await checkService();await loadProviderState();applyAsrSettings(state.settingsData);await refreshLocalModels();await refreshProjects();if(!state.projects.length){const p=await api('/projects',{method:'POST',body:JSON.stringify({name:'我的第一期单人播客'})});await refreshProjects()}
  const saved=localStorage.getItem('solo-project');await openProject(state.projects.find(p=>p.id===saved)?.id||state.projects[0].id);setInterval(poll,1800)});
