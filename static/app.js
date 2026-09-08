'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const state={project:null,projects:[],selected:null,panel:'setup',filter:'all',inputMode:'text',busy:false,polling:false,previewKey:'',pending:0,startingAction:null,saving:Promise.resolve(),arollSupported:false,ttsStatus:null,asrModel:'base',providerCatalog:null,settingsData:null,providerStatus:null,preflight:null};
let previewAnimation=0;
const voiceCatalog={
  'azure-v1':{
    Chinese:[['zh-CN-XiaoxiaoNeural','中文女声 · 晓晓（默认）'],['zh-CN-XiaoyiNeural','中文女声 · 晓伊'],['zh-CN-liaoning-XiaobeiNeural','中文女声 · 晓北（辽宁）'],['zh-CN-shaanxi-XiaoniNeural','中文女声 · 晓妮（陕西）'],['zh-CN-XiaoxiaoMultilingualNeural-V2','中文女声 · 晓晓多语种 V2'],['zh-CN-YunjianNeural','中文男声 · 云健'],['zh-CN-YunxiNeural','中文男声 · 云希'],['zh-CN-YunxiaNeural','中文男声 · 云夏'],['zh-CN-YunyangNeural','中文男声 · 云扬']],
    English:[['en-US-AvaNeural','英文女声 · Ava'],['en-US-EmmaNeural','英文女声 · Emma'],['en-US-JennyNeural','英文女声 · Jenny'],['en-US-AndrewNeural','英文男声 · Andrew'],['en-US-BrianNeural','英文男声 · Brian'],['en-US-GuyNeural','英文男声 · Guy']]
  }
};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=s=>{s=Math.max(0,Number(s)||0);return (s>=3600?Math.floor(s/3600)+':':'')+String(Math.floor(s/60)%60).padStart(2,'0')+':'+String(Math.floor(s)%60).padStart(2,'0')};
const safeURL=s=>/^https?:\/\//.test(s||'')?s:'';
const cameraLabel=s=>({medium:'中景',medium_close:'中近景',close:'近景'}[s]||s||'');
const changeLabel=s=>({hold:'保持长镜头',cut_in:'切近',cut_out:'切远',push_in:'轻微推近',pull_out:'轻微拉远',broll_insert:'短 B-roll 插入',return_primary:'回主镜头',broll:'B-roll'}[s]||s||'');
const media=name=>state.project?`/api/projects/${state.project.id}/files/${String(name).split('/').map(encodeURIComponent).join('/')}`:'';
const host=()=>media(state.project?.host_asset||state.project?.portrait_poster||state.project?.portrait||'assets/placeholder.jpg');
const hostMedia=()=>media(state.project?.host_media_asset||state.project?.portrait||'assets/placeholder.jpg');
const hostIsVideo=()=>state.project?.host_media_kind==='video';
function toast(message){$('#toast').textContent=message;$('#toast').style.display='block';clearTimeout(toast.timer);toast.timer=setTimeout(()=>$('#toast').style.display='none',5500)}
async function api(path,options={}){
  const headers=options.body instanceof FormData?{}:{'Content-Type':'application/json'};
  const response=await fetch('/api'+path,{...options,headers:{...headers,...options.headers}});
  if(!response.ok){let data;try{data=await response.json()}catch{data={detail:`请求失败 (${response.status})`}}throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail))}
  return response.json();
}
async function guarded(fn){try{return await fn()}catch(e){toast(e.message);return null}}
function pid(){return state.project.id}
function inferProvider(){return 'azure-v1'}
function updateVoiceOptions(preferred){
  const provider=$('#ttsProvider').value,language=$('#ttsLanguage').value,options=voiceCatalog[provider]?.[language]||[];
  $('#ttsSpeaker').innerHTML=options.map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');
  $('#ttsSpeaker').value=options.some(v=>v[0]===preferred)?preferred:options[0]?.[0]||'';
}
function updateTtsNotice(){
  const info=state.ttsStatus?.providers?.['azure-v1'];
  $('#ttsNotice').textContent=info?.ready===false?'Azure TTS V1 组件待安装，请重新运行「安装工作台.bat」。':'Azure TTS V1 · 联网配音，无需 Azure Key；生成后可直接下载，也可使用下方播放器试听。原稿会发送到微软语音服务。';
}
function arollName(){return state.providerStatus?.aroll?.short_name||state.project?.aroll_provider?.short_name||'人物口型'}
function syncRatioUi(value){
  value=Number(value);$('#ratioValue').textContent=value+'%';
  $$('[data-ratio-preset]').forEach(button=>{const active=Number(button.dataset.ratioPreset)===value;button.classList.toggle('active',active);button.setAttribute('aria-checked',String(active))});
}
function renderProviderSummaries(){
  const status=state.providerStatus;if(!status)return;
  $('#arollBadge').textContent=status.aroll.short_name||status.aroll.name;
  $('#globalLlmSummary').textContent='跟随全局：'+status.llm.name;
  $('#globalBrollSummary').textContent='跟随全局：'+status.broll.name;
  $('#globalArollSummary').textContent='跟随全局：'+status.aroll.name;
}
async function loadProviderState(){
  if(!state.providerCatalog)state.providerCatalog=await api('/providers');
  [state.settingsData,state.providerStatus]=await Promise.all([api('/settings'),api('/providers/status')]);
  renderProviderSummaries();
}
async function refreshPreflight(){
  if(!state.project)return;
  try{state.preflight=await api('/projects/'+pid()+'/preflight')}catch{state.preflight=null}
  renderStatus();
}
async function refreshProjects(){state.projects=await api('/projects');renderProjects()}
function renderProjects(){
  $('#projectCount').textContent=state.projects.length;
  $('#projects').innerHTML=state.projects.map(p=>`<button class="project-item ${p.id===state.project?.id?'active':''}" data-project="${p.id}"><span class="project-icon">▤</span><span><strong>${esc(p.name)}</strong><small>${p.duration?fmt(p.duration)+' · 单人播客':'等待文字 / 音频'}</small></span></button>`).join('');
  $$('[data-project]').forEach(b=>b.onclick=()=>guarded(()=>openProject(b.dataset.project)));
}
async function openProject(id){
  if(state.project)await flushScript();
  await state.saving;
  $('#audioPlayer').pause();$('#brollPreview').pause();
  state.project=await api('/projects/'+id);if(!state.project.shots.length)state.panel='setup';state.selected=state.project.shots[0]?.id;state.previewKey='';localStorage.setItem('solo-project',id);
  const audio=$('#audioPlayer');if(state.project.audio)audio.src=media(state.project.audio);else{audio.removeAttribute('src');audio.load()}
  renderAll();renderProjects();await refreshPreflight();
}
async function reload(){const p=await api('/projects/'+pid());state.project=p;if(!p.shots.some(s=>s.id===state.selected))state.selected=p.shots[0]?.id;renderAll();await refreshPreflight()}
function renderAll(){
  const p=state.project;if(!p)return;
  const player=$('#audioPlayer'),url=p.audio?media(p.audio):'';
  if(url&&player.getAttribute('src')!==url){player.src=url;player.load()}
  const draft=readDraft(p.id)||p.script||{text:'',provider:'azure-v1',speaker:'zh-CN-XiaoxiaoNeural',language:'Chinese',speed:1};
  if(document.activeElement!==$('#scriptText'))$('#scriptText').value=draft.text;
  $('#ttsProvider').value=inferProvider(draft);
  $('#ttsLanguage').value=[...$('#ttsLanguage').options].some(o=>o.value===draft.language)?draft.language:'Chinese';
  updateVoiceOptions(draft.speaker);$('#ttsSpeed').value=String(draft.speed||1);updateTtsNotice();
  setInputMode(localStorage.getItem('solo-input-'+p.id)||(p.script||!p.audio?'text':'audio'));
  $('#downloadVoice').classList.toggle('hidden',!p.tts);$('#downloadVoice').href=url;
  if(document.activeElement!==$('#projectName'))$('#projectName').value=p.name;
  $('#crumbTitle').textContent=p.name;
  $('#audioFilename').textContent=p.audio_name||'点击或拖入音频';$('#audioFilename').title=p.audio_name||'';
  $('#portraitThumb').src=host();$('#previewEmpty').classList.toggle('hidden',!!p.audio);
  const hostVideo=$('#portraitVideo');$('#portraitThumb').classList.toggle('hidden',hostIsVideo());hostVideo.classList.toggle('hidden',!hostIsVideo());
  if(hostIsVideo()){
    const url=hostMedia();if(hostVideo.getAttribute('src')!==url){hostVideo.src=url;hostVideo.load()}
    hostVideo.play().catch(()=>{});
  }else{hostVideo.pause();hostVideo.removeAttribute('src');hostVideo.load()}
  $('#portraitLabel').textContent=p.portrait_name?`${p.portrait_name}${hostIsVideo()?' · '+Number(p.portrait_duration).toFixed(1)+' 秒 · 循环视频':' · 图片'}`:(hostIsVideo()?'默认循环视频 · 我的素材/循环视频.mp4':'默认播客主持人 · 单人正脸清晰');
  $('#totalTime').textContent=fmt(p.duration);$('#scrubber').max=p.duration||100;
  $('#ratio').value=p.options.broll_ratio;syncRatioUi(p.options.broll_ratio);
  $('#resolution').value=p.options.resolution;$('#subtitlesToggle').checked=p.options.subtitles;renderProviderSummaries();
  $('#downloadSrt').classList.toggle('hidden',!p.segments.length);$('#downloadSrt').href='/api/projects/'+pid()+'/subtitles';
  renderPipeline();renderStatus();renderTimeline();renderShots();renderShotDetail();renderExports();setPanel(state.panel);syncPreview();
}
function runningPipelineStage(p){
  const j=p?.job;if(j?.status!=='running')return -1;
  const direct={tts:0,transcribe:0,plan:1,materials:2,aroll:2,render:3};
  if(j.action!=='all')return direct[j.action]??-1;
  const stage=String(j.stage||'');
  if(['文字配音','本地转录','转录'].includes(stage))return 0;
  if(['语义判断','规则剪辑'].includes(stage))return 1;
  if(['匹配素材','A-roll 对口型'].includes(stage))return 2;
  if(['合成视频','校验输出'].includes(stage))return 3;
  return 0;
}
function renderPipeline(){
  const p=state.project,b=p.shots.filter(s=>s.kind==='B'),ready=b.filter(s=>s.asset).length,a=p.shots.filter(s=>s.kind==='A'),aReady=a.filter(s=>s.aroll_ready).length;
  const stages=[['文字 / 音频',p.audio?fmt(p.duration)+' · 已就绪':'声音是故事的起点',!!p.audio],['理解与分镜',p.shots.length?`${p.narrative_segments?.length||0} 个叙事段 · ${p.shots.length} 个视觉镜头`:p.segments.length?`${p.segments.length} 个候选段 · 待判断`:'时间戳 · 语义分类',!!p.shots.length],['匹配画面',p.shots.length?`口型 ${aReady}/${a.length} · 素材 ${ready}/${b.length}`:'人物口型 · 场景素材',!!p.shots.length&&ready===b.length&&aReady===a.length],['导出成片',p.exports.some(e=>e.revision===p.revision)?'当前版本已导出':'预览 · 字幕 · MP4',p.exports.some(e=>e.revision===p.revision)]];
  const next=stages.findIndex(s=>!s[2]),running=runningPipelineStage(p);
  $('#pipeline').innerHTML=stages.map((s,i)=>{const working=i===running;return `<div class="pipeline-step ${s[2]?'done':i===next?'current':''} ${working?'running':''}"><span class="pipeline-number">${s[2]?'✓':String(i+1).padStart(2,'0')}</span><div class="pipeline-copy"><strong>${s[0]}</strong><small>${esc(s[1])}</small></div>${working?`<span class="pipeline-worker" role="img" aria-label="${s[0]}正在运行"><img src="/pipeline-animations/step${i+1}-frame1.png" alt=""><img src="/pipeline-animations/step${i+1}-frame2.png" alt=""></span>`:''}</div>`}).join('');
}
function renderStatus(){
  const p=state.project,j=p.job;state.busy=j?.status==='running'||state.pending>0||!!state.startingAction;
  $('#serviceNotice').classList.toggle('hidden',state.arollSupported);
  $('#serviceNotice').textContent='工作台有更新尚未载入。请运行目录中的「重启工作台.bat」，页面将自动检查更新状态，项目和已生成内容会保留。';
  const noB=p.shots.length&&!p.shots.some(s=>s.kind==='B')&&p.options.broll_ratio>0;
  $('#planNotice').classList.toggle('hidden',!noB);
  $('#planNotice').textContent='本次分镜全部为人物镜头，没有安排 B-roll。可重新「生成语义分镜」，或在镜头详情中改为 B-roll 后匹配素材。';
  document.body.classList.toggle('busy',state.busy);
  const show=!!j;$('#statusbar').classList.toggle('hidden',!show);
  if(show){$('#statusbar').classList.toggle('error',['error','cancelled'].includes(j.status));$('#statusbar .status-message').textContent=j.message;$('#statusbar .progress i').style.width=j.progress+'%';$('#cancelJob').classList.toggle('hidden',j.status!=='running');$('#statusbar .progress').classList.toggle('hidden',j.status!=='running')}
  const sourceReady=!!(p.audio||$('#scriptText').value.trim()),activeIssues=(state.preflight?.issues||[]).filter(issue=>!(sourceReady&&issue.code==='source')),providersReady=!activeIssues.length,launchReady=sourceReady&&state.arollSupported&&providersReady,launch=$('#quickLaunch');
  const oneClickGenerating=state.startingAction==='all'||(j?.status==='running'&&j.action==='all');
  const currentVersionExported=p.exports.some(e=>e.revision===p.revision);
  launch.classList.toggle('pending',!launchReady);
  launch.classList.toggle('generating',oneClickGenerating);
  $('#autoButton').innerHTML=`<span>${oneClickGenerating?'…':'✦'}</span> ${oneClickGenerating?'正在生成':currentVersionExported?'重新生成':'一键生成播客'}`;
  if(state.busy){$('#quickLaunchStatus').textContent=oneClickGenerating?'正在生成':'正在处理中';$('#quickLaunchHelp').textContent=j?.message||'当前任务完成后即可继续。'}
  else if(launchReady){$('#quickLaunchStatus').textContent=currentVersionExported?'当前版本已生成':'准备就绪后';$('#quickLaunchHelp').textContent=currentVersionExported?'再次点击会为当前版本重新生成成片':'自动完成配音 / 转录、分镜、素材与口型'}
  else{const missing=[];if(!sourceReady)missing.push('输入文稿或导入音频');if(!state.arollSupported)missing.push('重启工作台载入更新');if(sourceReady&&activeIssues.length)missing.push(activeIssues[0].message.replace(/^还差一步[：:]\s*/,''));$('#quickLaunchStatus').textContent='尚未准备就绪';$('#quickLaunchHelp').textContent='还差：'+missing.join('；')}
  $('#autoButton').disabled=!sourceReady||state.busy||!state.arollSupported;$('#exportButton').disabled=!p.shots.length||state.busy||!state.arollSupported;
  $('#ttsButton').disabled=!$('#scriptText').value.trim()||state.busy||!state.arollSupported;
  $('#scriptText').disabled=state.busy;$('#installAroll').disabled=state.busy;$('#installWav2lip').disabled=state.busy;
  $('#transcribeButton').disabled=!p.audio||state.busy||!state.arollSupported;$('#planButton').disabled=!p.segments.length||state.busy||!state.arollSupported;$('#materialsButton').disabled=!p.shots.some(s=>s.kind==='B')||state.busy||!state.arollSupported;
  $('#useHostMaterial').disabled=state.busy||!$('#hostMaterial').value;
  $('#resumeJob').classList.toggle('hidden',!['error','cancelled'].includes(j?.status));
  $('#resumeJob').disabled=state.busy||!state.arollSupported;
  $('#playButton').disabled=!p.audio;$$('#shotPanel button, #shotPanel input, #shotPanel textarea, #setupPanel select, #quickStart select, #ratio, #subtitlesToggle, #projectName, #audioUpload, #portraitUpload, #srtUpload').forEach(e=>e.disabled=state.busy);
}
function renderTimeline(){
  const p=state.project;$('#ruler').innerHTML=Array.from({length:6},(_,i)=>`<span>${fmt(p.duration*i/5)}</span>`).join('');
  $('#visualTimeline').innerHTML=p.shots.map((s,i)=>`<button title="${esc(s.title)} · ${fmt(s.start)}" class="timeline-clip ${s.kind==='B'?'b':''} ${s.id===state.selected?'selected':''}" style="flex:${s.end-s.start}" data-seek="${s.id}">${s.kind}${String(i+1).padStart(2,'0')}</button>`).join('');
  $$('[data-seek]').forEach(b=>b.onclick=()=>selectShot(b.dataset.seek,true));
  $('#waveform').innerHTML=(p.waveform.length?p.waveform:[]).map(v=>`<i style="height:${Math.max(6,v*100)}%"></i>`).join('');
  $('#waveform').onclick=e=>{if(!p.audio)return;const rect=e.currentTarget.getBoundingClientRect();seek((e.clientX-rect.left)/rect.width*p.duration)};
}
function renderShots(){
  const p=state.project;$('#shotCount').textContent=p.shots.length+' 个镜头';const visible=p.shots.filter(s=>state.filter==='all'||s.kind===state.filter);
  if(!visible.length){$('#shotList').innerHTML=`<div class="empty-shots"><strong>${p.shots.length?'这个分类还没有镜头':'镜头会从你的讲述里自然生长。'}</strong>${p.shots.length?'切换到「全部」查看其他镜头。':'先输入文字生成配音，或导入音频后转录，再生成规则分镜。<br>LLM 理解语义，程序决定 A/B 与真实时长。'}</div>`;return}
  $('#shotList').innerHTML=visible.map(s=>{
    const i=p.shots.indexOf(s),missing=s.kind==='B'?!s.asset:!s.aroll_ready;
    let thumb=s.kind==='A'?(s.aroll_ready?`<video class="shot-thumb" src="${media(s.aroll_asset)}#t=0.1" muted preload="metadata" aria-label="${esc(arollName())} 人物口型"></video>`:`<img class="shot-thumb" src="${host()}" alt="人物出镜">`):s.asset?(/\.(jpg|png|webp)$/i.test(s.asset)?`<img class="shot-thumb" src="${media(s.asset)}" alt="B-roll 图片">`:`<video class="shot-thumb" src="${media(s.asset)}#t=0.1" muted preload="metadata" aria-label="B-roll 素材"></video>`):`<div class="shot-thumb">素材待补</div>`;
    return `<article class="shot-card ${s.id===state.selected?'selected':''}" data-shot="${s.id}" tabindex="0" role="button" aria-label="镜头 ${i+1} ${esc(s.title)}"><span class="shot-number">${String(i+1).padStart(2,'0')}</span>${thumb}<div class="shot-content"><div class="shot-meta"><span class="kind-badge ${s.kind==='B'?'b':''}">${s.kind}-ROLL</span><span>${fmt(s.start)} — ${fmt(s.end)}</span><span>${(s.end-s.start).toFixed(1)}s</span></div><h4>${esc(s.title)}</h4><p>${esc(s.text)}</p></div><span class="shot-state ${missing?'missing':''}">${missing?(s.kind==='A'?'待生成口型':'待匹配'):(s.kind==='A'?'口型已就绪':'已匹配')} ↗</span></article>`;
  }).join('');
  $$('[data-shot]').forEach(card=>{card.onclick=()=>selectShot(card.dataset.shot,true);card.onkeydown=e=>{if(e.key==='Enter')selectShot(card.dataset.shot,true)}});
}
async function selectShot(id,jump=false){await state.saving;state.selected=id;state.panel='shot';renderTimeline();renderShots();renderShotDetail();setPanel('shot');if(jump){const s=state.project.shots.find(s=>s.id===id);seek(s.start)}}
function setPanel(name){state.panel=name;['setup','shot','exports'].forEach(n=>$('#'+n+'Panel').classList.toggle('hidden',n!==name));$$('[data-panel]').forEach(b=>b.classList.toggle('active',b.dataset.panel===name))}
function renderShotDetail(){
  const p=state.project,s=p.shots.find(s=>s.id===state.selected),root=$('#shotPanel');
  if(!s){root.innerHTML='<div class="panel-empty">选择一个分镜，<br>查看语义与素材详情。</div>';return}
  const i=p.shots.indexOf(s),video=s.asset&&/\.mp4$/i.test(s.asset),looped=s.source?.duration>0&&s.source.duration-(s.media_start||0)<s.end-s.start;
  const framing=[cameraLabel(s.camera),changeLabel(s.visual_change)].filter(Boolean).join(' · '),cut=s.cut_reason?`· 切点：${esc(s.cut_reason)}${Number.isFinite(s.cut_score)?` (${s.cut_score})`:''}`:'';
  root.innerHTML=`<div class="eyebrow">VISUAL SHOT ${String(i+1).padStart(2,'0')}</div><h3 class="detail-title">${esc(s.title)}</h3><div class="detail-info">${fmt(s.start)} — ${fmt(s.end)} · ${(s.end-s.start).toFixed(2)} 秒${framing?' · '+esc(framing):''}</div><p class="source-note">语义：${esc(s.semantic_type||'—')} · 视觉价值：${Number.isFinite(s.visual_value)?s.visual_value:'—'} · 人物价值：${Number.isFinite(s.host_value)?s.host_value:'—'} · 可视化对象：${esc(s.visual_subject||'无')} ${cut}</p>${s.editorial_review?`<p class="help export-warning">${esc(s.editorial_review)}</p>`:''}<div class="detail-switch"><button class="button ${s.kind==='A'?'active':''}" data-kind="A">A-roll 人物</button><button class="button ${s.kind==='B'?'active':''}" data-kind="B">B-roll 素材</button></div><div class="detail-text">${esc(s.text)}</div><label class="detail-field">镜头标题<input id="shotTitle" value="${esc(s.title)}"></label><label class="detail-field">程序决策说明<textarea id="shotReason">${esc(s.reason)}</textarea></label><label class="detail-field">与下一镜头的交界（秒）<input id="shotEnd" type="number" step="0.01" value="${s.end}" ${i===p.shots.length-1?'disabled':''}></label><p class="source-note">修改交界会同时调整相邻镜头，总时长保持不变。</p>${s.kind==='B'?`<div class="divider"></div><label class="detail-field">素材检索词（每行一个）<textarea id="shotKeywords">${esc(s.keywords.join('\n'))}</textarea></label><p class="help">描述能看见的具体画面，例如 “old library books”。修改后可重新搜索候选。</p><button id="searchShot" class="button wide">搜索候选素材</button><label class="button wide">导入本地视频 / 图片<input id="localBroll" type="file" accept="video/*,image/png,image/jpeg,image/webp" hidden></label>${video?`<label class="detail-field">素材入点（秒）<input id="mediaStart" type="number" step="0.1" min="0" value="${s.media_start||0}"></label>`:''}${!s.asset?`<p class="export-warning help">尚未匹配素材，预览与导出暂用人物图。${esc(s.material_error||'')}</p>`:''}${looped?'<p class="help export-warning">此素材短于镜头时长，成片会循环使用该片段。</p>':''}${s.source?`<p class="source-note">当前素材：${esc(s.source.provider)} · ${esc(s.source.author||s.source.name||'')} ${safeURL(s.source.page)?`<a class="source-link" href="${esc(s.source.page)}" target="_blank" rel="noreferrer">来源 ↗</a>`:''}</p>`:''}<div id="candidates">${s.candidates.slice().sort((a,b)=>Number(b.id===s.source?.id)-Number(a.id===s.source?.id)).slice(0,3).map(c=>`<div class="candidate">${safeURL(c.thumbnail)?`<img src="${esc(c.thumbnail)}" alt="${esc(c.query)}" loading="lazy" referrerpolicy="no-referrer">`:''}<div class="candidate-info"><small>${esc(c.provider)} · ${c.duration} 秒 · ${c.width}×${c.height}</small><small>${esc(c.author)} / ${esc(c.query)}</small><a href="${esc(safeURL(c.page))}" class="source-link" target="_blank" rel="noreferrer">查看素材来源 ↗</a><button class="button" data-candidate="${esc(c.id)}">${s.source?.id===c.id?'✓ 当前使用':'选用这个素材'}</button></div></div>`).join('')}</div>`:`<div class="divider"></div><p class="help">MuseTalk 1.5 · ${s.aroll_ready?'口型已生成，预览和导出使用这段视频。':(hostIsVideo()?'口型尚未生成或输入已变化，当前预览为原循环视频。导出前会自动生成口型。':'口型尚未生成或输入已变化，当前预览暂用人物图。导出前会自动生成。')}</p>${s.aroll_error?`<p class="help export-warning">${esc(s.aroll_error)}</p>`:''}<button id="generateShotAroll" class="button wide">${s.aroll_ready?'重新生成这一镜口型':'生成这一镜口型'}</button><p class="help">只使用 ${fmt(s.start)}–${fmt(s.end)} 的对应原音频。已生成的历史视频会保留。</p>`}`;
  $$('[data-kind]').forEach(b=>b.onclick=()=>patchShot({kind:b.dataset.kind}));
  $('#shotTitle').onchange=e=>patchShot({title:e.target.value});$('#shotReason').onchange=e=>patchShot({reason:e.target.value});$('#shotEnd').onchange=e=>patchShot({end:Number(e.target.value)});
  if(s.kind==='B'){
    $('#shotKeywords').onchange=e=>patchShot({keywords:e.target.value.split('\n').map(s=>s.trim()).filter(Boolean)});
    $('#searchShot').onclick=()=>guarded(()=>doRequest(`/shots/${s.id}/search`,{}));
    $('#localBroll').onchange=e=>uploadFile('broll',e.target.files[0],s.id);
    if($('#mediaStart'))$('#mediaStart').onchange=e=>patchShot({media_start:Number(e.target.value)});
    $$('[data-candidate]').forEach(b=>b.onclick=()=>guarded(()=>doRequest(`/shots/${s.id}/select`,{candidate_id:b.dataset.candidate})));
  }
  if($('#generateShotAroll')){$('#generateShotAroll').onclick=()=>startJob('aroll',s.id);$('#generateShotAroll').disabled=!state.arollSupported;
    if(s.kind==='A'&&((i>0&&p.shots[i-1].kind==='A')||(i+1<p.shots.length&&p.shots[i+1].kind==='A')))$('#generateShotAroll').nextElementSibling.textContent='为避免切景别时闪帧，会同步重生这一段连续 A-roll；各镜头仍只使用对应原音频。历史视频会保留。';}
  if(state.busy)$$('#shotPanel button,#shotPanel input,#shotPanel textarea').forEach(e=>e.disabled=true);
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
  const p=state.project;$('#exportsPanel').innerHTML='<h3 class="detail-title">成片与交付文件</h3><p class="help">每次导出单独保留。修改分镜后，已有成片不会自动更新。</p>'+(p.exports.length?p.exports.slice().reverse().map(e=>`<div class="export-card"><strong>${new Date(e.created_at*1000).toLocaleString('zh-CN')}</strong><p>${esc(e.size)} · ${fmt(e.duration)} · ${e.revision===p.revision?'当前版本':'历史版本'}</p>${e.fallbacks?`<p class="export-warning">${e.fallbacks} 段 B-roll 使用人物图占位</p>`:''}${e.looped?`<p class="help">${e.looped} 段素材循环播放</p>`:''}<a href="${media(e.file)}" target="_blank" class="button">播放成片 ↗</a> <a href="${media(e.file)}" download="${esc(p.name)}.mp4" class="button">下载 MP4</a><p><a class="source-link" href="${media(e.file.replace('podcast.mp4','subtitles.srt'))}" download>字幕 SRT</a> · <a class="source-link" href="${media(e.file.replace('podcast.mp4','manifest.json'))}" download>镜头与来源清单</a></p></div>`).join(''):'<div class="panel-empty">还没有导出的成片。<br>完成分镜后，在「制作设置」底部点击「导出视频」。</div>');
}
function seek(t){const audio=$('#audioPlayer');if(!state.project?.audio)return;audio.currentTime=Math.min(Math.max(0,t),state.project.duration);syncPreview(true)}
function syncPreview(force=false){
  const p=state.project;if(!p)return;const audio=$('#audioPlayer'),video=$('#brollPreview'),t=audio.currentTime||0;
  $('#currentTime').textContent=fmt(t);$('#scrubber').value=t;$('#playButton').textContent=audio.paused?'▶':'Ⅱ';
  const shot=p.shots.find(s=>t>=s.start&&t<s.end)||p.shots.at(-1),hasB=shot?.kind==='B'&&shot.asset,hasA=shot?.kind==='A'&&shot.aroll_ready,sourceVideo=!hasA&&!hasB&&shot?.kind!=='B'&&hostIsVideo(),visual=hasA?shot.aroll_asset:hasB?shot.asset:sourceVideo?p.host_media_asset:null;
  const isVideo=visual&&/\.(mp4|webm|mov|mkv|m4v)$/i.test(visual),key=visual?(hasA?'aroll|'+visual:(shot?.id||'source')+'|'+visual+'|'+(shot?.media_start||0)):'host|'+host();
  $('#currentKind').textContent=shot?.kind==='B'?(hasB?'B-ROLL':'B-ROLL · 人物图代替'):(hasA?'A-ROLL · '+arollName():sourceVideo?'A-ROLL · 原循环视频 · 待生成口型':'A-ROLL · 待生成口型');
  const baseScale=shot?.kind==='A'?(shot.camera==='close'?1.40:shot.camera==='medium_close'?1.22:1):1,progress=shot?Math.max(0,Math.min(1,(t-shot.start)/Math.max(.001,shot.end-shot.start))):0;
  const motionScale=shot?.motion==='push_in'?1+.08*progress:shot?.motion==='pull_out'?1.08-.08*progress:1,scale=baseScale*motionScale;
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
  const caption=p.options.subtitles?(p.captions||[]).find(s=>t>=s.start&&t<s.end):null;$('#previewCaption').textContent=caption?.text||'';
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
function showPreflight(check){
  const dialog=$('#preflightDialog');$('#preflightIssues').innerHTML=check.issues.map(issue=>`<p><strong>${esc(issue.message)}</strong></p>`).join('');
  $('#preflightInstall').classList.toggle('hidden',!check.issues.some(issue=>issue.action==='install'));dialog.showModal();
}
async function startJob(action,shotId=null){
  try{await flushScript()}catch(e){toast(e.message);return}
  await state.saving;
  await checkService();renderStatus();
  if(!state.arollSupported){toast('请先运行「重启工作台.bat」载入更新，再继续生成。');return}
  if(action==='all'){
    const check=await guarded(()=>api('/projects/'+pid()+'/preflight'));if(!check)return;
    state.preflight=check;renderStatus();if(!check.ok){showPreflight(check);return}
  }
  if((action==='transcribe'&&state.project.segments.length)||(action==='plan'&&state.project.shots.length)){
    if(!await confirmReplace(action==='transcribe'?'重新转录会重建本期字幕，并清除当前分镜。已导出的成片和原始素材会保留。':'重新分镜会替换当前镜头编辑和素材选择。已导出的成片和素材文件会保留。'))return;
  }
  state.startingAction=action;renderStatus();
  try{await guarded(async()=>{await api(`/projects/${pid()}/jobs`,{method:'POST',body:JSON.stringify({action,shot_id:shotId})});await reload();if(action==='render'||action==='all')setPanel('exports')})}
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
    try{await api('/projects/'+pid()+'/upload',{method:'POST',body:data});if(kind==='audio'){localStorage.removeItem('solo-script-'+pid());localStorage.setItem('solo-input-'+pid(),'audio')}await reload();if(kind==='audio'){$('#audioPlayer').src=media(state.project.audio);seek(0)}toast('导入完成')}
    finally{state.pending--;renderStatus()}
  });
}
async function patchOptions(values){await guarded(async()=>{await api('/projects/'+pid(),{method:'PATCH',body:JSON.stringify({options:values})});await reload()})}
async function poll(){
  if(state.polling||!state.project)return;state.polling=true;
  try{
    if(!state.lastHealth||Date.now()-state.lastHealth>15000){await checkService();state.lastHealth=Date.now();renderStatus()}
    const p=await api('/projects/'+pid()),old=state.project,changed=JSON.stringify(p.job)!==JSON.stringify(old.job);
    if(state.project.id!==p.id)return;
    if(changed){
      if(p.job?.status==='running'){state.project.job=p.job;renderStatus();renderPipeline()}
      else if(document.activeElement?.matches('input,textarea,select')&&!state.busy){/* Do not replace an active editor. */}
      else{state.project=p;if(old.job?.action==='setup_models')await loadProviderState();renderAll();await refreshPreflight();await refreshProjects();if(old.job?.status==='running')toast(p.job.message)}
    }
  }catch(e){/* Keep current project visible during a temporary reconnect. */}finally{state.polling=false}
}
$('#newProject').onclick=()=>{$('#newDialog').showModal();$('#newForm input').focus()};
$$('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('#newForm').onsubmit=e=>{e.preventDefault();guarded(async()=>{const p=await api('/projects',{method:'POST',body:JSON.stringify({name:new FormData(e.target).get('name')})});$('#newDialog').close();e.target.reset();await refreshProjects();await openProject(p.id)})};
$('#projectName').onchange=e=>guarded(async()=>{await api('/projects/'+pid(),{method:'PATCH',body:JSON.stringify({name:e.target.value})});state.project.name=e.target.value;$('#crumbTitle').textContent=e.target.value;await refreshProjects()});
$('#audioUpload').onchange=e=>uploadFile('audio',e.target.files[0]);$('#portraitUpload').onchange=e=>uploadFile('portrait',e.target.files[0]);$('#srtUpload').onchange=e=>uploadFile('srt',e.target.files[0]);
$('#hostMaterial').onchange=()=>renderStatus();
$('#useHostMaterial').onclick=()=>guarded(async()=>{
  await state.saving;state.pending++;renderStatus();toast('正在导入人物素材…');
  try{await api('/projects/'+pid()+'/host-material',{method:'POST',body:JSON.stringify({name:$('#hostMaterial').value})});await reload();toast('人物素材已更新，可生成 A-roll 口型')}
  finally{state.pending--;renderStatus()}
});
api('/host-materials').then(items=>{$('#hostMaterial').innerHTML='<option value="">选择人物图片或循环视频…</option>'+items.map(x=>`<option value="${esc(x.name)}">${esc(x.name)}</option>`).join('')}).catch(()=>{});
const drop=$('#audioDrop');drop.ondragover=e=>{e.preventDefault();drop.classList.add('dragover')};drop.ondragleave=()=>drop.classList.remove('dragover');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('dragover');if(!state.busy)uploadFile('audio',e.dataTransfer.files[0])};
$('#ratio').oninput=e=>syncRatioUi(e.target.value);$('#ratio').onchange=e=>patchOptions({broll_ratio:Number(e.target.value)});
$$('[data-ratio-preset]').forEach(button=>button.onclick=()=>patchOptions({broll_ratio:Number(button.dataset.ratioPreset)}));
$('#resolution').onchange=e=>patchOptions({resolution:e.target.value});$('#subtitlesToggle').onchange=e=>patchOptions({subtitles:e.target.checked});
$('#transcribeButton').onclick=()=>startJob('transcribe');$('#planButton').onclick=()=>startJob('plan');$('#materialsButton').onclick=()=>startJob('materials');$('#autoButton').onclick=()=>startJob('all');$('#exportButton').onclick=()=>startJob('render');
$('#cancelJob').onclick=()=>guarded(async()=>{const r=await api('/projects/'+pid()+'/cancel',{method:'POST',body:'{}'});toast(r.message)});
$('#resumeJob').onclick=()=>{const j=state.project.job;startJob(['all','tts','setup_models','transcribe','plan','materials','aroll','render'].includes(j?.action)?j.action:'all',j?.shot_id||null)};
$$('[data-filter]').forEach(b=>b.onclick=()=>{state.filter=b.dataset.filter;$$('[data-filter]').forEach(x=>x.classList.toggle('active',x===b));renderShots()});
$$('[data-panel]').forEach(b=>b.onclick=()=>setPanel(b.dataset.panel));
$('#playButton').onclick=()=>guarded(async()=>{const a=$('#audioPlayer');if(a.paused)await a.play();else a.pause();syncPreview()});
$('#muteButton').onclick=()=>{const a=$('#audioPlayer');a.muted=!a.muted;$('#muteButton').textContent=a.muted?'×':'♪'};
$('#scrubber').oninput=e=>seek(Number(e.target.value));
['timeupdate','play','pause','ended','seeked'].forEach(event=>$('#audioPlayer').addEventListener(event,()=>{syncPreview(event==='seeked');if(event==='play')startPreviewAnimation()}));
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
function syncProviderFields(){
  const form=$('#settingsForm'),llm=form.elements.llm_provider.value,broll=form.elements.broll_provider.value,aroll=form.elements.aroll_provider.value,custom=form.elements.aroll_custom_type.value;
  $('#llmCustomFields').classList.toggle('hidden',llm!=='custom');
  const llmMeta=selectedMetadata('llm',llm);$('#llmKeyLink').textContent=llm==='deepseek'?'获取 DeepSeek API Key ↗':'API Key 由您的服务商提供';$('#llmKeyLink').href=llmMeta.key_url||'#';$('#llmKeyLink').classList.toggle('disabled-link',!llmMeta.key_url);
  $$('[data-broll-key]').forEach(group=>group.classList.toggle('hidden',group.dataset.brollKey!==broll));
  const brollMeta=selectedMetadata('broll',broll);$('#brollKeyLink').textContent=`获取 ${brollMeta.name} API Key ↗`;$('#brollKeyLink').href=brollMeta.key_url||'#';
  $('#musetalkFields').classList.toggle('hidden',aroll!=='musetalk');$('#wav2lipFields').classList.toggle('hidden',aroll!=='wav2lip');$('#customArollFields').classList.toggle('hidden',aroll!=='custom');
  $('#comfyuiFields').classList.toggle('hidden',custom!=='comfyui');$('#externalArollFields').classList.toggle('hidden',custom!=='external_api');
}
function renderSettingsStatus(){
  const s=state.providerStatus;if(!s)return;
  $('#connectionStatus').textContent=`分镜 AI：${s.llm.name}${s.llm.configured?'已配置':'待配置'} · B-roll：${s.broll.name}${s.broll.configured?'已配置':'待配置'} · A-roll：${s.aroll.name}${s.aroll.ready?'已就绪':'待准备'}`;
  $('#llmState').textContent=s.llm.configured?'✓ 已配置':'○ 尚未配置';$('#brollState').textContent=s.broll.configured?'✓ 已配置':'○ 尚未配置';$('#arollState').textContent=s.aroll.ready?'✓ 已就绪':'○ 尚未准备';
  $('#arollStatusText').textContent=(s.aroll.id==='musetalk'?(s.aroll.ready?'✓ ':'○ '):'')+(s.aroll.message||'');
  $('#wav2lipStatusText').textContent=s.aroll.id==='wav2lip'?(s.aroll.message||'○ 尚未安装'):'○ 尚未安装';
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
  for(const key of ['llm_provider','llm_custom_name','llm_custom_base_url','llm_custom_model','broll_provider','aroll_provider','aroll_custom_type','aroll_comfyui_url','aroll_comfyui_workflow','aroll_comfyui_workflow_hash','aroll_person_node','aroll_audio_node','aroll_output_node','aroll_external_name','aroll_external_url','aroll_external_model','asr_model','asr_device','aroll_batch_size'])if(form.elements[key])form.elements[key].value=s[key]??'';
  for(const key of ['llm_api_key','pexels_api_key','pixabay_api_key','aroll_external_api_key']){form.elements[key].value='';form.elements[key].placeholder=s[key+'_configured']?'••••••••••••':'尚未配置'}
  $('#workflowStatus').textContent=s.aroll_comfyui_workflow_hash?'✓ workflow_api.json 已导入':'导入 workflow_api.json';
  syncProviderFields();renderSettingsStatus();$('#settingsDialog').showModal();
}
$('#globalApiButton').onclick=()=>guarded(openGlobalApiSettings);
$('#settingsButton').onclick=()=>guarded(openGlobalApiSettings);
$$('[data-open-settings]').forEach(button=>button.onclick=()=>guarded(openGlobalApiSettings));
$('#settingsForm').onsubmit=e=>{e.preventDefault();guarded(async()=>{const body=settingsFormBody();state.settingsData=await api('/settings',{method:'PUT',body:JSON.stringify(body)});applyAsrSettings(state.settingsData);await loadProviderState();await refreshPreflight();$('#settingsDialog').close();toast('连接与设置已保存')})};
function applyAsrSettings(s){
  state.asrModel=['large-v3','small','base'].includes(s?.asr_model)?s.asr_model:'base';
  const advanced=$('#settingsForm').elements.asr_model;if(advanced)advanced.value=state.asrModel;
}
function readDraft(id){try{return JSON.parse(localStorage.getItem('solo-script-'+id)||'null')}catch{return null}}
function scriptValue(){return {text:$('#scriptText').value,provider:$('#ttsProvider').value,speaker:$('#ttsSpeaker').value,language:$('#ttsLanguage').value,speed:Number($('#ttsSpeed').value)}}
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
$('#ttsButton').onclick=()=>guarded(()=>startJob('tts'));
async function installSelectedAroll(){if($('#settingsDialog').open)$('#settingsDialog').close();if($('#preflightDialog').open)$('#preflightDialog').close();await startJob('setup_models')}
$('#installAroll').onclick=()=>guarded(installSelectedAroll);$('#installWav2lip').onclick=()=>guarded(installSelectedAroll);
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
