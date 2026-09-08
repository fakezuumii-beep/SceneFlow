"""On-demand, resumable installer for SOLO's isolated Wav2Lip runtime.

The optional upstream component is intentionally not bundled with SOLO.  This
installer only runs after the user acknowledges the upstream non-commercial
terms in the UI (or explicitly passes the CLI acknowledgement for development
smoke tests).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
ENGINES = ROOT / 'engines'
SOURCE_REPO = 'https://github.com/Rudrabha/Wav2Lip'
SOURCE_REVISION = 'bac9a81e63ecc153202353372e5724b83d9e6322'
SOURCE_ARCHIVE_SIZE = 468_596
SOURCE_ARCHIVE_SHA256 = 'd22eca3f2a3c32c3dc2bffe50453e82ca8c26245034ac9deb930ec759597f7c5'
PYTHON_VERSION = '3.10.19'
TORCH_VERSION = '2.8.0'
TORCH_INDEX_CUDA = 'https://download.pytorch.org/whl/cu126'
TORCH_INDEX_CPU = 'https://download.pytorch.org/whl/cpu'
ADAPTER_VERSION = 'solo-wav2lip-torchscript-v1'
PROVIDER_VERSION = 'wav2lip-provider-v2'
LICENSE_REFERENCE = f'wav2lip-noncommercial-{SOURCE_REVISION[:12]}-sd-gan-v1'

# These are the two files linked by the pinned upstream README.  The current
# GAN link serves a TorchScript model named Wav2Lip-SD-GAN.pt; it is not the
# legacy optimizer checkpoint expected by upstream inference.py.
CHECKPOINT_NAME = 'Wav2Lip-SD-GAN.pt'
CHECKPOINT_SIZE = 145_829_145
CHECKPOINT_SHA256 = '180cfd49d31d47f195d5bfc62830ffe2c40724b7bbbce6faadc73ac6ab1a3b8e'
CHECKPOINT_URL = ('https://drive.usercontent.google.com/download?'
                  'id=15G3U08c8xsCkOqQxE38Z2XXDnPcOptNk&export=download&confirm=t')
CHECKPOINT_PAGE = 'https://drive.google.com/file/d/15G3U08c8xsCkOqQxE38Z2XXDnPcOptNk/view'
S3FD_NAME = 's3fd.pth'
S3FD_SIZE = 89_843_225
S3FD_SHA256 = '619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543'
S3FD_URL = 'https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth'


def emit(percent: int, message: str):
    print(f'[{max(0, min(100, int(percent))):03d}] {message}', flush=True)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verified(path: Path, size: int, sha256: str) -> bool:
    return path.is_file() and path.stat().st_size == size and digest(path) == sha256


def download(url: str, path: Path, size: int | None = None, sha256: str | None = None,
             progress: int = 45):
    """Download to .part, resume with Range, and replace only after validation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and (size is None or path.stat().st_size == size) and (
            sha256 is None or digest(path) == sha256):
        emit(progress, f'已校验：{path.name}')
        return
    part = path.with_suffix(path.suffix + '.part')
    for attempt in range(4):
        try:
            offset = part.stat().st_size if part.exists() else 0
            headers = {'Range': f'bytes={offset}-'} if offset else {}
            with requests.get(url, headers=headers, stream=True, timeout=(20, 90)) as response:
                if response.status_code == 416:
                    part.unlink(missing_ok=True)
                    continue
                response.raise_for_status()
                append = bool(offset and response.status_code == 206)
                if append and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
                    raise RuntimeError('下载续传范围不正确')
                with part.open('ab' if append else 'wb') as stream:
                    last = time.monotonic()
                    for block in response.iter_content(2 * 1024 * 1024):
                        if block:
                            stream.write(block)
                        if time.monotonic() - last >= 2:
                            emit(progress, f'下载 {path.name}：{stream.tell() / 1024 ** 2:.0f} MB')
                            last = time.monotonic()
            if size is not None and part.stat().st_size != size:
                raise RuntimeError(f'{path.name} 文件大小校验失败')
            if sha256 is not None and digest(part) != sha256:
                part.unlink(missing_ok=True)
                raise RuntimeError(f'{path.name} SHA256 校验失败')
            os.replace(part, path)
            emit(progress, f'完成：{path.name}')
            return
        except (requests.RequestException, OSError, RuntimeError):
            if attempt == 3:
                raise
            time.sleep(2)


def runtime_python() -> Path:
    return ENGINES / 'wav2lip-env' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def source_root() -> Path:
    return ENGINES / 'Wav2Lip'


def checkpoint_path() -> Path:
    return source_root() / 'checkpoints' / CHECKPOINT_NAME


def detector_path() -> Path:
    return source_root() / 'face_detection' / 'detection' / 'sfd' / S3FD_NAME


def ready_path() -> Path:
    return ENGINES / 'wav2lip-env' / 'ready.json'


def uv_command() -> list[str]:
    bundled = ROOT / '.runtime' / 'uv' / 'uv.exe'
    if bundled.is_file():
        return [str(bundled)]
    found = shutil.which('uv')
    if found:
        return [found]
    raise RuntimeError('缺少 uv，无法准备独立 Wav2Lip Python 环境')


def command(args: list[str | Path], cwd: Path | None = None):
    subprocess.run([str(value) for value in args], cwd=cwd, check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)


def install_source():
    target = source_root()
    marker = target / 'workbench-source.json'
    try:
        record = json.loads(marker.read_text(encoding='utf-8'))
        if (record.get('revision') == SOURCE_REVISION and
                (target / 'face_detection/detection/sfd/net_s3fd.py').is_file() and
                (target / 'models/wav2lip.py').is_file()):
            emit(20, 'Wav2Lip 固定源码已校验')
            return
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    emit(15, '下载 Wav2Lip 固定版本源码…')
    archive = ENGINES / 'downloads' / f'Wav2Lip-{SOURCE_REVISION}.zip'
    download(f'{SOURCE_REPO}/archive/{SOURCE_REVISION}.zip', archive,
             SOURCE_ARCHIVE_SIZE, SOURCE_ARCHIVE_SHA256, 20)
    unpack = ENGINES / f'.Wav2Lip-{SOURCE_REVISION}.tmp'
    if unpack.exists():
        shutil.rmtree(unpack)
    with zipfile.ZipFile(archive) as zipped:
        zipped.extractall(unpack)
    roots = [item for item in unpack.iterdir() if item.is_dir()]
    if len(roots) != 1 or not (roots[0] / 'face_detection/detection/sfd/net_s3fd.py').is_file():
        raise RuntimeError('Wav2Lip 源码包结构无效')
    if target.exists():
        shutil.rmtree(target)
    roots[0].replace(target)
    shutil.rmtree(unpack, ignore_errors=True)
    marker.write_text(json.dumps({'repo': SOURCE_REPO, 'revision': SOURCE_REVISION,
                                  'archive_sha256': SOURCE_ARCHIVE_SHA256}, indent=2), encoding='utf-8')


def install_checkpoint(manual: Path | None = None):
    target = checkpoint_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = manual or (ENGINES / 'downloads' / f'manual-{CHECKPOINT_NAME}')
    if staged.is_file():
        emit(42, '校验用户选择的官方 Wav2Lip 模型…')
        if not verified(staged, CHECKPOINT_SIZE, CHECKPOINT_SHA256):
            raise RuntimeError('所选模型不是当前支持的官方 Wav2Lip-SD-GAN.pt（SHA256 不匹配）')
        if not verified(target, CHECKPOINT_SIZE, CHECKPOINT_SHA256):
            shutil.copy2(staged, target)
        emit(55, '官方 Wav2Lip 模型已校验')
    else:
        try:
            emit(42, '下载官方 Wav2Lip 模型…')
            download(CHECKPOINT_URL, target, CHECKPOINT_SIZE, CHECKPOINT_SHA256, 55)
        except Exception as exc:
            raise RuntimeError('官方模型自动下载失败。请在设置中打开官方说明，选择本地下载的 '
                               f'{CHECKPOINT_NAME} 后重试。详情：{exc}') from exc
    emit(58, '下载并校验官方 S3FD 人脸检测模型…')
    download(S3FD_URL, detector_path(), S3FD_SIZE, S3FD_SHA256, 62)


def setup_runtime(cpu: bool = False) -> Path:
    uv = uv_command()
    env = ENGINES / 'wav2lip-env'
    python = runtime_python()
    if not python.is_file():
        emit(65, f'准备独立 Python {PYTHON_VERSION} 环境…')
        command(uv + ['venv', str(env), '--python', PYTHON_VERSION])
    index = TORCH_INDEX_CPU if cpu else TORCH_INDEX_CUDA
    emit(70, '安装固定版本 PyTorch 运行环境…')
    command(uv + ['pip', 'install', '--python', str(python), f'torch=={TORCH_VERSION}',
                  '--index-url', index])
    emit(80, '安装 Wav2Lip 最小推理依赖…')
    command(uv + ['pip', 'install', '--python', str(python), '-r',
                  str(ROOT / 'requirements-wav2lip.txt')])
    return python


def runtime_info(python: Path) -> dict:
    script = (
        "import json,sys,torch,cv2,librosa,scipy;"
        "sys.path.insert(0,sys.argv[1]);import face_detection;"
        "f=open(sys.argv[2],'rb');m=torch.jit.load(f,map_location='cpu');f.close();"
        "print(json.dumps({'python':sys.version.split()[0],'torch':torch.__version__,"
        "'cuda_runtime':torch.version.cuda,'cuda_available':torch.cuda.is_available(),"
        "'opencv':cv2.__version__,'librosa':librosa.__version__}))"
    )
    output = subprocess.check_output([str(python), '-c', script, str(source_root()),
                                      str(checkpoint_path())], text=True, cwd=ROOT,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    return json.loads(output.strip().splitlines()[-1])


def environment_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob('*') if item.is_file())


def write_ready(info: dict):
    record = {
        'provider': 'wav2lip', 'provider_version': PROVIDER_VERSION,
        'adapter_version': ADAPTER_VERSION, 'license_reference': LICENSE_REFERENCE,
        'repo': SOURCE_REPO, 'source_revision': SOURCE_REVISION,
        'checkpoint': CHECKPOINT_NAME, 'checkpoint_size': CHECKPOINT_SIZE,
        'checkpoint_sha256': CHECKPOINT_SHA256, 'checkpoint_source': CHECKPOINT_PAGE,
        's3fd': S3FD_NAME, 's3fd_size': S3FD_SIZE, 's3fd_sha256': S3FD_SHA256,
        'python': info['python'], 'torch': info['torch'],
        'cuda_runtime': info.get('cuda_runtime'),
        'device': 'cuda' if info.get('cuda_available') else 'cpu',
        'environment_size': environment_size(ENGINES / 'wav2lip-env'),
        'installed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    ready_path().write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')


def installation_status() -> dict:
    python = runtime_python()
    marker = source_root() / 'workbench-source.json'
    ready = ready_path()
    required = [python, ROOT / 'wav2lip_worker.py', marker,
                source_root() / 'models' / 'wav2lip.py',
                source_root() / 'face_detection' / 'detection' / 'sfd' / 'net_s3fd.py',
                checkpoint_path(), detector_path(), ready]
    installed_artifacts = [path for path in required if path != ROOT / 'wav2lip_worker.py']
    if not any(path.exists() for path in installed_artifacts):
        return {'ready': False, 'installed': False,
                'message': '尚未安装 · 仅限个人 / 研究 / 非商业用途'}
    if not all(path.is_file() for path in required):
        return {'ready': False, 'installed': True, 'message': 'Wav2Lip 环境需要修复'}
    try:
        source = json.loads(marker.read_text(encoding='utf-8'))
        record = json.loads(ready.read_text(encoding='utf-8'))
        valid = (
            source.get('revision') == SOURCE_REVISION and
            source.get('repo') == SOURCE_REPO and
            source.get('archive_sha256') == SOURCE_ARCHIVE_SHA256 and
            record.get('provider_version') == PROVIDER_VERSION and
            record.get('adapter_version') == ADAPTER_VERSION and
            record.get('license_reference') == LICENSE_REFERENCE and
            record.get('repo') == SOURCE_REPO and
            record.get('source_revision') == SOURCE_REVISION and
            record.get('checkpoint') == CHECKPOINT_NAME and
            record.get('checkpoint_size') == CHECKPOINT_SIZE and
            record.get('checkpoint_sha256') == CHECKPOINT_SHA256 and
            record.get('s3fd') == S3FD_NAME and
            record.get('s3fd_size') == S3FD_SIZE and
            record.get('s3fd_sha256') == S3FD_SHA256 and
            record.get('python') == PYTHON_VERSION and
            str(record.get('torch', '')).split('+')[0] == TORCH_VERSION and
            record.get('device') in ('cuda', 'cpu') and
            checkpoint_path().stat().st_size == CHECKPOINT_SIZE and
            detector_path().stat().st_size == S3FD_SIZE
        )
        if not valid:
            raise ValueError('manifest mismatch')
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {'ready': False, 'installed': True, 'message': 'Wav2Lip 环境需要修复'}
    device = record.get('device', 'cpu')
    message = 'Wav2Lip 已就绪 · 本地 GPU' if device == 'cuda' else 'Wav2Lip 已就绪 · CPU（速度可能很慢）'
    return {'ready': True, 'installed': True, 'message': message, 'device': device,
            'manifest': record}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--acknowledge-license', action='store_true')
    parser.add_argument('--cpu', action='store_true')
    parser.add_argument('--checkpoint', type=Path)
    args = parser.parse_args()
    if not args.acknowledge_license:
        raise RuntimeError('必须先阅读并确认 Wav2Lip 第三方非商业使用限制')
    emit(10, '检查 Wav2Lip 独立运行环境')
    install_source()
    install_checkpoint(args.checkpoint)
    cpu = args.cpu or not bool(shutil.which('nvidia-smi'))
    python = setup_runtime(cpu)
    emit(94, '运行 Wav2Lip 导入和模型自检…')
    info = runtime_info(python)
    write_ready(info)
    emit(100, 'Wav2Lip 安装和校验完成')


if __name__ == '__main__':
    main()
