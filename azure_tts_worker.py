"""Azure TTS V1 (edge-tts) worker with resumable phrase audio."""
from __future__ import annotations
import asyncio, inspect, json, os, queue, subprocess, sys, threading, time, wave
from pathlib import Path

import edge_tts

from atomic_files import atomic_json as write_json
from tts_common import split_script
from worker_progress import atomic_json as write_progress


def rate_percent(value):
    try: rate=float(value)
    except (TypeError,ValueError): rate=1.0
    rate=max(.5,min(2.0,rate))
    percent=round((rate-1.0)*100)
    return f'{percent:+d}%'


def communicate(text,voice,rate):
    kwargs={'rate':rate_percent(rate)}
    if 'boundary' in inspect.signature(edge_tts.Communicate).parameters:
        kwargs['boundary']='WordBoundary'
    return edge_tts.Communicate(text,voice,**kwargs)


def stream_chunks(client,on_chunk,timeout):
    """Consume current sync streams and older async streams with a hard timeout."""
    events=queue.Queue();finished=object()
    def produce():
        try:
            if hasattr(client,'stream_sync'):
                for chunk in client.stream_sync():events.put(('chunk',chunk))
            else:
                async def consume():
                    async for chunk in client.stream():events.put(('chunk',chunk))
                asyncio.run(consume())
            events.put(('done',finished))
        except BaseException as exc:events.put(('error',exc))
    threading.Thread(target=produce,daemon=True).start()
    deadline=time.monotonic()+timeout
    while True:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError(f'Azure TTS V1 单次请求超过 {timeout:g} 秒')
        try:kind,value=events.get(timeout=min(.5,remaining))
        except queue.Empty:continue
        if kind=='chunk':on_chunk(value)
        elif kind=='error':raise value
        else:return


def valid_wav(path,sample_rate):
    try:
        with wave.open(str(path),'rb') as audio:
            return audio.getframerate()==sample_rate and audio.getnchannels()==1 and audio.getnframes()>sample_rate*.1
    except (OSError,wave.Error):return False


def synthesize_phrase(text,voice,rate,path,ffmpeg,timeout):
    temp_mp3=path.with_suffix('.tmp.mp3');temp_wav=path.with_suffix('.tmp.wav')
    for attempt in range(3):
        temp_mp3.unlink(missing_ok=True);temp_wav.unlink(missing_ok=True)
        try:
            client=communicate(text.strip(),voice,rate)
            with temp_mp3.open('wb') as output:
                stream_chunks(client,lambda chunk:output.write(chunk['data']) if chunk.get('type')=='audio' else None,timeout)
            if not temp_mp3.is_file() or temp_mp3.stat().st_size<256:raise RuntimeError('服务没有返回有效音频')
            result=subprocess.run([str(ffmpeg),'-y','-v','error','-i',str(temp_mp3),'-ac','1','-ar','24000','-c:a','pcm_s16le',str(temp_wav)],capture_output=True,text=True)
            if result.returncode or not valid_wav(temp_wav,24000):
                raise RuntimeError((result.stderr or '音频解码失败').strip()[-800:])
            os.replace(temp_wav,path);temp_mp3.unlink(missing_ok=True);return
        except Exception:
            temp_mp3.unlink(missing_ok=True);temp_wav.unlink(missing_ok=True)
            if attempt==2:raise
            time.sleep(attempt+1)


def main(request_path):
    req=json.loads(Path(request_path).read_text(encoding='utf-8'))
    folder=Path(req['folder']);folder.mkdir(parents=True,exist_ok=True)
    parts=[part for part in split_script(req['text']) if part.strip()]
    voice=req['speaker'];rate=float(req.get('speed',1.0));timeout=float(req.get('timeout',45))
    sample_rate=24000;segments=[];cursor=0
    def status(done,message):write_progress(folder/'progress.json',{'done':done,'total':len(parts),'message':message})
    status(0,'正在连接 Azure TTS V1 · '+voice)
    for index,text in enumerate(parts):
        path=folder/f'{index:05d}.wav'
        if not valid_wav(path,sample_rate):
            status(index,f'正在联网配音 {index+1}/{len(parts)} 段 · Azure TTS V1')
            synthesize_phrase(text,voice,rate,path,req['ffmpeg'],timeout)
        with wave.open(str(path),'rb') as audio:frames=audio.getnframes()
        segments.append({'id':index,'start':round(cursor/sample_rate,3),'end':round((cursor+frames)/sample_rate,3),'text':text.strip()})
        cursor+=frames+(int(sample_rate*.16) if index<len(parts)-1 else 0)
        status(index+1,f'已完成联网配音 {index+1}/{len(parts)} 段')
    temp=folder/'combined.tmp.wav'
    with wave.open(str(temp),'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(sample_rate)
        for index in range(len(parts)):
            with wave.open(str(folder/f'{index:05d}.wav'),'rb') as source:output.writeframes(source.readframes(source.getnframes()))
            if index<len(parts)-1:output.writeframes(b'\0\0'*int(sample_rate*.16))
    os.replace(temp,folder/'combined.wav')
    write_json(folder/'result.json',{'segments':segments,'duration':cursor/sample_rate,'engine':'Azure TTS V1','provider':'azure-v1','speaker':voice,'language':req['language'],'speed':rate,'device':'online'})


if __name__=='__main__':main(sys.argv[1])
