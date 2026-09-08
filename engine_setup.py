"""Resumable installer for the workbench-owned MuseTalk runtime."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, time, zipfile
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
ENGINES = ROOT / 'engines'
OFFLINE = ROOT / '.offline'
MUSETALK_REPO = 'TMElyralab/MuseTalk'
MUSETALK_REV = '0a89dec45a0192b824e3cf4daf96c239440c5ed8'
MUSETALK_MODEL_REV = '3ef28bc5cff08c90ad8178a25f1b570cd800170f'
VAE_REPO = 'stabilityai/sd-vae-ft-mse'
VAE_REV = '31f26fdeee1355a5c34592e401dd41e45d25a493'
WHISPER_REPO = 'openai/whisper-tiny'
WHISPER_REV = '169d4a4341b33bc18d8881c4b69c2e104e1cc0af'
OPENCV_ZOO_REV = '47534e27c9851bb1128ccc0102f1145e27f23f98'
YUNET_SHA256 = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'
YUNET_URL = f'https://raw.githubusercontent.com/opencv/opencv_zoo/{OPENCV_ZOO_REV}/models/face_detection_yunet/face_detection_yunet_2023mar.onnx'

def emit(message): print(message, flush=True)

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def download(url,path,sha=None,size=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and (size is None or path.stat().st_size==size) and (not sha or digest(path)==sha):
        emit('已校验：'+path.name);return
    part=path.with_suffix(path.suffix+'.part')
    for attempt in range(4):
        try:
            offset=part.stat().st_size if part.exists() else 0
            headers={'Range':f'bytes={offset}-'} if offset else {}
            with requests.get(url,headers=headers,stream=True,timeout=(20,90)) as response:
                if response.status_code==416:part.unlink(missing_ok=True);continue
                response.raise_for_status();append=bool(offset and response.status_code==206)
                if append and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):
                    raise RuntimeError('下载续传范围不正确')
                with part.open('ab' if append else 'wb') as stream:
                    last=time.monotonic()
                    for block in response.iter_content(2*1024*1024):
                        if block:stream.write(block)
                        if time.monotonic()-last>3:
                            emit(f'下载 {path.name}：{stream.tell()/1024**2:.0f} MB');last=time.monotonic()
            if size and part.stat().st_size!=size:raise RuntimeError('文件大小校验失败')
            if sha and digest(part)!=sha:
                part.unlink(missing_ok=True);raise RuntimeError('SHA256 校验失败')
            os.replace(part,path);emit('完成：'+path.name);return
        except (requests.RequestException,RuntimeError):
            if attempt==3:raise
            time.sleep(2)

def model(repo,rev,folder,only):
    wanted=set(only)
    manifest_path=folder/'installed.json'
    try:
        installed=json.loads(manifest_path.read_text(encoding='utf-8'))
        records={item['file']:item for item in installed.get('files',[])}
        if installed.get('repo')==repo and installed.get('revision')==rev and all(
            (folder/name).is_file() and name in records and
            (not records[name].get('size') or (folder/name).stat().st_size==records[name]['size']) and
            (not records[name].get('sha256') or digest(folder/name)==records[name]['sha256'])
            for name in only
        ):
            emit(f'已校验本地模型：{repo}')
            return
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError):
        pass
    response=requests.get(f'https://huggingface.co/api/models/{repo}/revision/{rev}?blobs=true',timeout=30)
    response.raise_for_status();info=response.json();manifest=[]
    for item in info['siblings']:
        name=item['rfilename']
        if name not in wanted:continue
        target=folder/name
        if not target.resolve().is_relative_to(folder.resolve()):raise ValueError('模型文件路径无效')
        sha=item.get('lfs',{}).get('sha256');size=item.get('size')
        download(f'https://huggingface.co/{repo}/resolve/{rev}/{name}',target,sha,size)
        manifest.append({'file':name,'size':target.stat().st_size,'sha256':sha or digest(target)})
    missing=wanted-{x['file'] for x in manifest}
    if missing:raise RuntimeError('模型仓库缺少文件：'+', '.join(sorted(missing)))
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'installed.json').write_text(json.dumps({'repo':repo,'revision':rev,'files':manifest},indent=2),encoding='utf-8')

def command(args):
    subprocess.run([str(x) for x in args],check=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)

def uv_command():
    bundled=ROOT/'.runtime'/'uv'/'uv.exe'
    if bundled.is_file():return [str(bundled)]
    if shutil.which('uv'):return [shutil.which('uv')]
    try:__import__('uv')
    except ImportError:command([sys.executable,'-m','pip','install','uv==0.8.22'])
    return [sys.executable,'-m','uv']

def install_source():
    target=ENGINES/'MuseTalk';marker=target/'workbench-source.json'
    try:
        if marker.is_file() and json.loads(marker.read_text())['revision']==MUSETALK_REV and (target/'musetalk/models/unet.py').is_file():return
        if (target/'.git').is_dir():
            revision=subprocess.check_output(['git','-C',str(target),'rev-parse','HEAD'],text=True).strip()
            if revision==MUSETALK_REV:
                marker.write_text(json.dumps({'repo':'https://github.com/TMElyralab/MuseTalk','revision':revision}));return
    except (OSError,ValueError,subprocess.SubprocessError):pass
    emit('下载 MuseTalk 官方源码…')
    archive=ENGINES/'downloads'/f'MuseTalk-{MUSETALK_REV}.zip'
    download(f'https://github.com/TMElyralab/MuseTalk/archive/{MUSETALK_REV}.zip',archive)
    unpack=ENGINES/f'.MuseTalk-{MUSETALK_REV}.tmp'
    if unpack.exists():shutil.rmtree(unpack)
    with zipfile.ZipFile(archive) as zipped:zipped.extractall(unpack)
    roots=[x for x in unpack.iterdir() if x.is_dir()]
    if len(roots)!=1 or not (roots[0]/'musetalk/models/unet.py').is_file():raise RuntimeError('MuseTalk 源码包结构无效')
    if target.exists():shutil.rmtree(target)
    roots[0].replace(target);shutil.rmtree(unpack,ignore_errors=True)
    marker.write_text(json.dumps({'repo':'https://github.com/TMElyralab/MuseTalk','revision':MUSETALK_REV}))

def setup_runtime(cpu=False):
    uv=uv_command();env=ENGINES/'media-env';py=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not py.exists():command(uv+['venv',str(env),'--python',sys.executable])
    wheelhouse=OFFLINE/'media-wheels'
    if wheelhouse.is_dir() and not cpu:
        emit('从随包依赖安装独立 CUDA 媒体环境…')
        common=['--no-index','--find-links',str(wheelhouse)]
        command(uv+['pip','install','--python',str(py)]+common+
                ['torch==2.8.0+cu126','torchaudio==2.8.0+cu126','torchvision==0.23.0+cu126'])
        command(uv+['pip','install','--python',str(py)]+common+['-r',str(ROOT/'requirements-media.txt')])
    else:
        emit('安装独立媒体环境（首次需要下载 PyTorch）…')
        command(uv+['pip','install','--python',str(py),'torch==2.8.0','torchaudio==2.8.0','torchvision==0.23.0',
                    '--index-url','https://download.pytorch.org/whl/'+('cpu' if cpu else 'cu126')])
        command(uv+['pip','install','--python',str(py),'-r',str(ROOT/'requirements-media.txt')])
    return env,py

def setup_models():
    source=ENGINES/'MuseTalk';models=source/'models'
    model(MUSETALK_REPO,MUSETALK_MODEL_REV,models,['musetalkV15/unet.pth','musetalkV15/musetalk.json'])
    model(VAE_REPO,VAE_REV,models/'sd-vae',['config.json','diffusion_pytorch_model.bin'])
    model(WHISPER_REPO,WHISPER_REV,models/'whisper',['config.json','pytorch_model.bin','preprocessor_config.json'])
    download(YUNET_URL,models/'face_detection_yunet_2023mar.onnx',sha=YUNET_SHA256)

def ready_manifest(env,device):
    files=[]
    for path in (ENGINES/'MuseTalk'/'models').rglob('*'):
        if path.is_file() and path.name!='installed.json':files.append({'file':path.relative_to(ENGINES/'MuseTalk').as_posix(),'size':path.stat().st_size})
    (env/'ready.json').write_text(json.dumps({'torch':'2.8.0',
                                              'musetalk_revision':MUSETALK_REV,
                                              'device':device,'files':files},indent=2),encoding='utf-8')

def remove_legacy_speech_runtime():
    """Remove the retired local speech model only after MuseTalk is healthy."""
    for name in ('ko'+'koro-82m','ko'+'koro-tts-env'):
        target=ENGINES/name
        if target.is_dir():shutil.rmtree(target)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cpu',action='store_true');args=parser.parse_args()
    if not shutil.which('nvidia-smi'):args.cpu=True
    install_source();env,py=setup_runtime(args.cpu);setup_models()
    command([py,'-c','import torch,cv2,diffusers,librosa; print("media runtime OK",torch.__version__)'])
    ready_manifest(env,'cpu' if args.cpu else 'cuda')
    remove_legacy_speech_runtime()
    emit('独立 MuseTalk 安装和校验完成，可以开始创作。')
