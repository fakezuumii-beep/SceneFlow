"""Isolated ASR process releases GPU memory on exit and downloads models on demand."""
import json, os, sys
from pathlib import Path
from speech_units import align_script_to_words, phrase_segments
from atomic_files import atomic_json
from worker_progress import atomic_json as write_progress

audio,output,status,model,device,language=sys.argv[1:7]
reference_path=Path(sys.argv[7]) if len(sys.argv)>7 else None
from faster_whisper import WhisperModel
import ctranslate2

def report(t,message):
    write_progress(Path(status),{'time':t,'message':message})

devices=['cuda','cpu'] if device=='auto' and ctranslate2.get_cuda_device_count()>0 else ['cpu' if device=='auto' else device]
for i,chosen in enumerate(devices):
    try:
        report(0,f'正在使用 {chosen.upper()} 加载 Whisper {model}')
        engine=WhisperModel(model,device=chosen,compute_type='float16' if chosen=='cuda' else 'int8',local_files_only=False,cpu_threads=4,num_workers=1)
        chunks,info=engine.transcribe(audio,language=language or None,beam_size=5,vad_filter=True,condition_on_previous_text=False,word_timestamps=True)
        segments=[];all_words=[];audio_end=0.0
        for s in chunks:
            words=[{'start':w.start,'end':w.end,'word':w.word} for w in (s.words or [])]
            all_words.extend(words);audio_end=max(audio_end,float(s.end))
            segments.extend(phrase_segments({'start':s.start,'end':s.end,'text':s.text.strip(),
                'words':words}))
            report(s.end,f'{chosen.upper()} 转录中 · 已处理 {s.end:.0f} 秒')
        alignment='asr-punctuation-v1';engine=f'faster-whisper {model} / {chosen}'
        if reference_path and reference_path.is_file():
            reference=reference_path.read_text(encoding='utf-8')
            segments=align_script_to_words(reference,all_words,0.0,audio_end)
            alignment='script-punctuation-word-v1';engine+=' + script alignment'
        atomic_json(Path(output),{'segments':segments,'language':info.language,'engine':engine,'alignment':alignment})
        break
    except Exception:
        if i==len(devices)-1: raise
        if 'engine' in globals(): del engine
        report(0,'GPU 转录不可用，正在回退到 CPU')
