"""Standalone MuseTalk 1.5 inference worker used by the workbench.

It keeps the neural networks loaded while processing every pending A-roll shot
in one request.  This module has no ComfyUI imports or HTTP dependency.
"""
from __future__ import annotations
import json, math, os, subprocess, sys, time
from pathlib import Path
import cv2
import numpy as np
import torch
from transformers import WhisperModel
from worker_progress import atomic_json

FPS=25

def frames(path):
    path=Path(path)
    if path.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.bmp'):
        frame=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
        if frame is None:raise RuntimeError('无法读取人物图片')
        return [frame]
    cap=cv2.VideoCapture(str(path));result=[]
    while True:
        ok,frame=cap.read()
        if not ok:break
        result.append(frame)
    cap.release()
    if not result:raise RuntimeError('无法读取人物视频')
    return result

def face_boxes(source,detector_model,margin=10):
    detector=cv2.FaceDetectorYN.create(str(detector_model),'',(320,320),score_threshold=.65,nms_threshold=.3,top_k=5000)
    result=[];previous=None
    for index,frame in enumerate(source):
        h,w=frame.shape[:2];detector.setInputSize((w,h));_,found=detector.detect(frame)
        if found is not None and len(found):
            face=max(found,key=lambda x:float(x[2]*x[3]));x,y,bw,bh=face[:4]
            pad_x=bw*.04;x1=max(0,int(x-pad_x));x2=min(w,int(math.ceil(x+bw+pad_x)))
            y1=max(0,int(y));y2=min(h,int(math.ceil(y+bh+margin)))
            if x2-x1>=32 and y2-y1>=32:previous=(x1,y1,x2,y2)
        if previous is None:raise RuntimeError(f'第 {index+1} 帧没有检测到清晰正脸，请更换人物素材')
        result.append(previous)
    return smooth_boxes(result)

def smooth_boxes(boxes,radius=2):
    """Centered median smoothing removes detector shimmer without adding lip-sync lag."""
    if len(boxes)<3:return boxes
    smoothed=[]
    values=np.asarray(boxes,dtype=np.float32)
    for index in range(len(boxes)):
        window=values[max(0,index-radius):min(len(boxes),index+radius+1)]
        x1,y1,x2,y2=np.median(window,axis=0).round().astype(int)
        if x2-x1<32 or y2-y1<32:x1,y1,x2,y2=boxes[index]
        smoothed.append((int(x1),int(y1),int(x2),int(y2)))
    return smoothed

def alpha_mask(width,height):
    mask=np.zeros((256,256),np.float32)
    cv2.ellipse(mask,(128,178),(102,71),0,0,360,1,-1)
    mask=cv2.GaussianBlur(mask,(31,31),0)
    return cv2.resize(mask,(width,height))[...,None]

class Engine:
    def __init__(self,repo,precision='float16'):
        sys.path.insert(0,str(repo))
        from musetalk.utils.audio_processor import AudioProcessor
        from musetalk.utils.utils import datagen,load_all_model
        from musetalk.utils.blending import get_image
        self.datagen=datagen;self.device=torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        models=repo/'models'
        self.vae,self.unet,self.pe=load_all_model(models/'musetalkV15/unet.pth','sd-vae',models/'musetalkV15/musetalk.json',self.device)
        self.dtype=torch.float16 if self.device.type=='cuda' and precision=='float16' else torch.float32
        self.pe=self.pe.to(device=self.device,dtype=self.dtype).eval()
        self.vae.vae=self.vae.vae.to(device=self.device,dtype=self.dtype).eval()
        self.unet.model=self.unet.model.to(device=self.device,dtype=self.dtype).eval()
        self.audio=AudioProcessor(str(models/'whisper'))
        self.whisper=WhisperModel.from_pretrained(str(models/'whisper')).to(device=self.device,dtype=self.dtype).eval()
        self.whisper.requires_grad_(False);self.detector=Path('models/face_detection_yunet_2023mar.onnx')
        self.get_image=get_image;self.parsers={}

    def face_parser(self,task):
        key=(int(task.get('left_cheek_width',90)),int(task.get('right_cheek_width',90)))
        if key not in self.parsers:
            from musetalk.utils.face_parsing import FaceParsing
            original_load=torch.load
            def trusted_weight_load(*args,**kwargs):
                # These two pinned files are SHA-256 verified by engine_setup.
                kwargs.setdefault('weights_only',False)
                return original_load(*args,**kwargs)
            try:
                torch.load=trusted_weight_load
                self.parsers[key]=FaceParsing(left_cheek_width=key[0],right_cheek_width=key[1])
            finally:
                torch.load=original_load
        return self.parsers[key]

    @torch.inference_mode()
    def run(self,task,progress,index,total):
        source=frames(task['video'])
        boxes=face_boxes(source,self.detector,max(0,min(40,int(task.get('extra_margin',10)))))
        latents=[]
        for frame,box in zip(source,boxes):
            x1,y1,x2,y2=box;crop=cv2.resize(frame[y1:y2,x1:x2],(256,256),interpolation=cv2.INTER_LANCZOS4)
            latents.append(self.vae.get_latents_for_unet(crop))
        features,length=self.audio.get_audio_feature(task['audio'],weight_dtype=self.dtype)
        chunks=self.audio.get_whisper_chunk(
            features,self.device,self.dtype,self.whisper,length,fps=FPS,
            audio_padding_length_left=max(0,min(5,int(task.get('audio_padding_left',2)))),
            audio_padding_length_right=max(0,min(5,int(task.get('audio_padding_right',2)))))
        batches=int(math.ceil(len(chunks)/task.get('batch_size',8)))
        output=Path(task['output']);output.parent.mkdir(parents=True,exist_ok=True)
        partial=output.with_suffix('.part.mp4')
        h,w=source[0].shape[:2]
        crf=max(0,min(30,int(task.get('crf',18))))
        ffmpeg=subprocess.Popen([task['ffmpeg'],'-y','-v','error','-f','rawvideo','-pixel_format','bgr24',
            '-video_size',f'{w}x{h}','-framerate',str(FPS),'-i','-','-an','-c:v','libx264','-preset','veryfast',
            '-crf',str(crf),'-pix_fmt','yuv420p','-movflags','+faststart',str(partial)],stdin=subprocess.PIPE)
        written=0
        try:
            generator=self.datagen(chunks,latents+latents[::-1],task.get('batch_size',8),device=self.device)
            for batch,(whisper_batch,latent_batch) in enumerate(generator):
                audio_batch=self.pe(whisper_batch.to(device=self.device,dtype=self.dtype))
                prediction=self.unet.model(latent_batch.to(device=self.device,dtype=self.dtype),torch.tensor([0],device=self.device),
                                           encoder_hidden_states=audio_batch).sample
                decoded=self.vae.decode_latents(prediction.to(device=self.device,dtype=self.vae.vae.dtype))
                for generated in decoded:
                    source_index=written%len(source);frame=source[source_index].copy();x1,y1,x2,y2=boxes[source_index]
                    patch=cv2.resize(generated,(x2-x1,y2-y1),interpolation=cv2.INTER_LANCZOS4)
                    if task.get('blend')=='face_parser':
                        frame=self.get_image(frame,patch,[x1,y1,x2,y2],
                                             mode=str(task.get('parsing_mode') or 'jaw'),
                                             fp=self.face_parser(task))
                    else:
                        alpha=alpha_mask(x2-x1,y2-y1)
                        frame[y1:y2,x1:x2]=(patch*alpha+frame[y1:y2,x1:x2]*(1-alpha)).astype(np.uint8)
                    ffmpeg.stdin.write(frame.tobytes());written+=1
                atomic_json(progress,{'task':index+1,'tasks':total,'batch':batch+1,'batches':batches,
                                      'message':f'A-roll {index+1}/{total} · 推理 {batch+1}/{batches}'})
        finally:
            if ffmpeg.stdin:ffmpeg.stdin.close()
            code=ffmpeg.wait()
        if code or written==0 or written!=len(chunks):raise RuntimeError('MuseTalk 没有生成完整视频')
        os.replace(partial,output)

def main(request_path):
    request=json.loads(Path(request_path).read_text(encoding='utf-8'));repo=Path(request['repo']).resolve();os.chdir(repo)
    progress=Path(request['progress']);atomic_json(progress,{'message':'正在加载 MuseTalk 1.5 模型…'})
    engine=Engine(repo,str(request.get('precision') or 'float16'));tasks=request['tasks']
    for index,task in enumerate(tasks):engine.run(task,progress,index,len(tasks))
    atomic_json(progress,{'task':len(tasks),'tasks':len(tasks),'message':'MuseTalk 推理完成'})

if __name__=='__main__':
    try:main(sys.argv[1])
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}',file=sys.stderr,flush=True);raise
