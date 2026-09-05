"""One isolated inference process per script; completed phrases survive retries."""
from __future__ import annotations
import hashlib, json, os, re, sys, wave
from pathlib import Path
from atomic_files import atomic_json as write_json
from worker_progress import atomic_json as write_progress

# 8 中文音色（lang_code='z'）+ 4 英文音色（lang_code='a'）= 12 个 Kokoro-82M 预设。
SPEAKERS = {
    'zf_xiaobei': '中文女声 · Xiaobei',
    'zf_xiaoni': '中文女声 · Xiaoni',
    'zf_xiaoxiao': '中文女声 · Xiaoxiao',
    'zf_xiaoyi': '中文女声 · Xiaoyi',
    'zm_yunjian': '中文男声 · Yunjian',
    'zm_yunxi': '中文男声 · Yunxi',
    'zm_yunxia': '中文男声 · Yunxia',
    'zm_yunyang': '中文男声 · Yunyang',
    'af_bella': '英文女声 · Bella',
    'af_nicole': '英文女声 · Nicole',
    'am_michael': '英文男声 · Michael',
    'am_adam': '英文男声 · Adam',
}
# Kokoro-82M 语言覆盖远小于 Qwen3-TTS；保留中英两个 Pipeline 即可。
LANGUAGES = ['Chinese', 'English']
LANG_CODE = {'Chinese': 'z', 'English': 'a'}
ZH_VOICES = {name for name in SPEAKERS if name.startswith(('zf_', 'zm_'))}
EN_VOICES = {name for name in SPEAKERS if name.startswith(('af_', 'am_'))}
DEFAULT_SPEAKER = 'zf_xiaoni'
LEGACY_SPEAKERS = {
    'Serena':'zf_xiaoni','Vivian':'zf_xiaoyi','Uncle_Fu':'zm_yunyang',
    'Dylan':'zm_yunjian','Eric':'zm_yunxi','Ryan':'am_michael','Aiden':'am_adam',
}

def split_script(text, limit=80):
    # Kokoro is noticeably weaker on very short utterances. Keep commas inside
    # a sentence, split at strong punctuation, and attach tiny sentences to a
    # neighbour while preserving every source character for subtitle timing.
    sentences=re.findall(r'.+?(?:[。！？!?；;\n]+|(?<=[a-zA-Z])[.](?=\s|$)|$)',text,flags=re.S)
    chunks=[]
    for sentence in sentences:
        while len(sentence)>limit:
            lower=limit//2
            cuts=[sentence.rfind(mark,lower,limit+1) for mark in ('，',',','：',':','、',' ')]
            cut=max(cuts)+1
            if cut<=lower:cut=limit
            chunks.append(sentence[:cut]);sentence=sentence[cut:]
        if sentence:chunks.append(sentence)
    result=[];pending=''
    for chunk in chunks:
        chunk=pending+chunk;pending=''
        if len(re.sub(r'\s|[，。！？!?；;,:：、]','',chunk))<8:
            pending=chunk
        else:result.append(chunk)
    if pending:
        if result and len(result[-1])+len(pending)<=limit:result[-1]+=pending
        else:result.append(pending)
    if ''.join(result)!=text: raise ValueError('原稿分段校验失败')
    return result

def signature(text,speaker,language,provider='kokoro',speed=1.0):
    # Preserve the original Kokoro key so existing phrase caches remain reusable.
    if provider=='kokoro' and float(speed)==1.0:payload=[text,speaker,language,'kokoro-82m-v1']
    else:payload=[text,speaker,language,provider,round(float(speed),3),'tts-v2']
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).hexdigest()[:24]

def main(request_path):
    req=json.loads(Path(request_path).read_text(encoding='utf-8'))
    # The model and voice embeddings are loaded by absolute local paths below.
    # Offline flags turn an accidental future Hub lookup into a clear failure.
    os.environ.setdefault('HF_HUB_OFFLINE','1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE','1')
    os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY','1')
    import numpy as np
    import soundfile as sf
    import torch
    from kokoro import KModel, KPipeline
    folder=Path(req['folder']);folder.mkdir(parents=True,exist_ok=True)
    parts=[p for p in split_script(req['text']) if p.strip()]
    speaker=req['speaker'] if req['speaker'] in SPEAKERS else DEFAULT_SPEAKER
    language=req['language'] if req['language'] in LANGUAGES else 'Chinese'
    # If the speaker is Chinese but language chosen as English, or vice versa,
    # snap to a matching voice so KPipeline is never asked for an unsupported one.
    if language=='Chinese' and speaker in EN_VOICES: speaker='zf_xiaoni'
    elif language=='English' and speaker in ZH_VOICES: speaker='af_bella'
    lang_code=LANG_CODE[language]
    speed=float(req.get('speed',1.0))
    device='cuda' if torch.cuda.is_available() else 'cpu'
    torch.set_num_threads(min(8,os.cpu_count() or 4));torch.manual_seed(42)
    def status(i,message):write_progress(folder/'progress.json',{'done':i,'total':len(parts),'message':message})
    status(0,'正在加载 Kokoro-82M · '+device)
    model_dir=Path(req['model']).resolve()
    config_path=model_dir/'config.json';weight_path=model_dir/'kokoro-v1_0.pth';voice_path=model_dir/'voices'/f'{speaker}.pt'
    if not config_path.is_file() or not weight_path.is_file() or not voice_path.is_file():
        raise RuntimeError('Kokoro-82M 本地模型或所选音色不完整，请在「连接与设置」中校验 / 修复本地媒体引擎')
    pipeline=None;segments=[];cursor=0;sr=24000
    for i,text in enumerate(parts):
        path=folder/f'{i:05d}.wav'
        valid=False
        if path.exists():
            try:
                info=sf.info(path);valid=info.samplerate==sr and info.frames>sr*.1 and info.channels==1
            except Exception: pass
        if not valid:
            if pipeline is None:
                model=KModel(repo_id=req.get('repo_id','hexgrad/Kokoro-82M'),config=str(config_path),model=str(weight_path)).to(device).eval()
                pipeline=KPipeline(lang_code=lang_code,repo_id=req.get('repo_id','hexgrad/Kokoro-82M'),model=model,device=device)
            status(i,f'正在配音 {i+1}/{len(parts)} 段 · {SPEAKERS[speaker]}')
            # A per-phrase seed also makes an interrupted run independent of cache hits.
            torch.manual_seed(42+i)
            chunks=[]
            with torch.inference_mode():
                # default split_pattern=r'\n+'; per-segment text has no newline,
                # so each call returns exactly one (graphemes, phonemes, audio).
                for result in pipeline(text.strip(),voice=str(voice_path),speed=speed):
                    audio=result.audio if hasattr(result,'audio') else result[2]
                    if audio is not None:chunks.append(audio.detach().cpu().numpy() if hasattr(audio,'detach') else audio)
            if not chunks:
                raise RuntimeError(f'第 {i+1} 段配音未返回有效音频，请重试')
            audio=np.concatenate(chunks) if len(chunks)>1 else np.asarray(chunks[0],dtype=np.float32)
            audio=np.asarray(audio,dtype=np.float32).reshape(-1)
            if not np.isfinite(audio).all() or len(audio)<sr*.1 or float(np.max(np.abs(audio)))<.0001:
                raise RuntimeError(f'第 {i+1} 段配音无有效声音，请重试')
            if len(audio)/sr>=60:raise RuntimeError(f'第 {i+1} 段疑似超长重复语音，请缩短该段文字后重试')
            temp=path.with_suffix('.tmp.wav');sf.write(temp,audio,sr,subtype='PCM_16');os.replace(temp,path)
        info=sf.info(path);frames=info.frames
        segments.append({'id':i,'start':round(cursor/sr,3),'end':round((cursor+frames)/sr,3),'text':text.strip()})
        cursor+=frames+(int(sr*.16) if i<len(parts)-1 else 0)
        status(i+1,f'已完成配音 {i+1}/{len(parts)} 段')
    with wave.open(str(folder/'combined.tmp.wav'),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(sr)
        for i in range(len(parts)):
            with wave.open(str(folder/f'{i:05d}.wav'),'rb') as src:out.writeframes(src.readframes(src.getnframes()))
            if i<len(parts)-1:out.writeframes(b'\0\0'*int(sr*.16))
    os.replace(folder/'combined.tmp.wav',folder/'combined.wav')
    write_json(folder/'result.json',{'segments':segments,'duration':cursor/sr,'engine':'Kokoro-82M','provider':'kokoro','speaker':speaker,'language':language,'speed':speed,'device':device})

if __name__=='__main__':main(sys.argv[1])
