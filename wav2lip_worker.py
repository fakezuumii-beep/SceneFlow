"""Isolated Wav2Lip inference worker.

Only this process imports Torch, OpenCV, librosa and the optional upstream
source.  It loads the model once, processes all contiguous A-roll runs, writes
silent 25 fps H.264 video, then exits so GPU memory can be released.
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import cv2
import librosa
import numpy as np
import torch
from scipy import signal

from worker_progress import atomic_json

FPS = 25
IMAGE_SIZE = 96
MEL_STEP = 16


def load_frames(path: str, frame_count: int) -> list[np.ndarray]:
    source = Path(path)
    if source.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.bmp'):
        frame = cv2.imdecode(np.fromfile(source, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError('无法读取人物图片')
        return [frame]
    capture = cv2.VideoCapture(str(source))
    frames = []
    while len(frames) < frame_count:
        ok, frame = capture.read()
        if not ok:
            break
        frames.append(frame)
    capture.release()
    if not frames:
        raise RuntimeError('无法读取人物视频')
    return frames


def smooth_boxes(boxes: list[tuple[int, int, int, int]], window: int = 5):
    values = np.asarray(boxes, dtype=np.float32)
    result = []
    for index in range(len(values)):
        sample = values[index:index + window]
        if len(sample) < window:
            sample = values[max(0, len(values) - window):]
        result.append(tuple(np.mean(sample, axis=0).astype(int)))
    return result


def detect_faces(frames: list[np.ndarray], repo: Path, device: str,
                 batch_size: int = 16) -> list[tuple[int, int, int, int]]:
    sys.path.insert(0, str(repo))
    import face_detection

    detector = face_detection.FaceAlignment(face_detection.LandmarksType._2D,
                                             flip_input=False, device=device)
    predictions = []
    current = batch_size
    while True:
        try:
            predictions.clear()
            for start in range(0, len(frames), current):
                predictions.extend(detector.get_detections_for_batch(
                    np.asarray(frames[start:start + current])))
            break
        except RuntimeError as exc:
            if current == 1:
                raise RuntimeError('人物画面过大，Wav2Lip 无法完成人脸检测') from exc
            current = max(1, current // 2)
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    boxes = []
    for index, (frame, found) in enumerate(zip(frames, predictions)):
        if found is None:
            raise RuntimeError(f'第 {index + 1} 帧没有检测到清晰正脸，请更换人物素材')
        x1, y1, x2, y2 = found
        height, width = frame.shape[:2]
        y2 = min(height, y2 + 10)
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
        if x2 - x1 < 32 or y2 - y1 < 32:
            raise RuntimeError(f'第 {index + 1} 帧的人脸区域过小，请更换更清晰的人物素材')
        boxes.append((x1, y1, x2, y2))
    return smooth_boxes(boxes)


def mel_spectrogram(path: str) -> np.ndarray:
    waveform, _ = librosa.load(path, sr=16000, mono=True)
    waveform = signal.lfilter([1, -0.97], [1], waveform)
    spectrum = librosa.stft(y=waveform, n_fft=800, hop_length=200, win_length=800)
    mel_basis = librosa.filters.mel(sr=16000, n_fft=800, n_mels=80, fmin=55, fmax=7600)
    minimum = np.exp(-100 / 20 * np.log(10))
    decibels = 20 * np.log10(np.maximum(minimum, np.dot(mel_basis, np.abs(spectrum)))) - 20
    mel = np.clip(8 * ((decibels + 100) / 100) - 4, -4, 4)
    if not np.isfinite(mel).all():
        raise RuntimeError('音频包含无法处理的数值')
    return mel


def mel_chunks(mel: np.ndarray, count: int) -> list[np.ndarray]:
    chunks = []
    multiplier = 80.0 / FPS
    for index in range(count):
        start = int(index * multiplier)
        end = start + MEL_STEP
        if end <= mel.shape[1]:
            chunk = mel[:, start:end]
        else:
            start = max(0, mel.shape[1] - MEL_STEP)
            chunk = mel[:, start:]
            if chunk.shape[1] < MEL_STEP:
                chunk = np.pad(chunk, ((0, 0), (0, MEL_STEP - chunk.shape[1])), mode='edge')
        chunks.append(chunk)
    return chunks


def batches(frames: list[np.ndarray], boxes: list[tuple[int, int, int, int]],
            mels: list[np.ndarray], batch_size: int):
    images, audio, originals, coordinates = [], [], [], []
    static = len(frames) == 1
    for index, mel in enumerate(mels):
        source_index = 0 if static else index % len(frames)
        frame = frames[source_index].copy()
        x1, y1, x2, y2 = boxes[source_index]
        face = cv2.resize(frame[y1:y2, x1:x2], (IMAGE_SIZE, IMAGE_SIZE))
        images.append(face)
        audio.append(mel)
        originals.append(frame)
        coordinates.append((x1, y1, x2, y2))
        if len(images) >= batch_size:
            yield prepare_batch(images, audio), originals, coordinates
            images, audio, originals, coordinates = [], [], [], []
    if images:
        yield prepare_batch(images, audio), originals, coordinates


def prepare_batch(images: list[np.ndarray], audio: list[np.ndarray]):
    image_batch = np.asarray(images)
    masked = image_batch.copy()
    masked[:, IMAGE_SIZE // 2:] = 0
    image_batch = np.concatenate((masked, image_batch), axis=3) / 255.0
    mel_batch = np.asarray(audio)[:, None, :, :]
    return image_batch.transpose(0, 3, 1, 2), mel_batch


class Engine:
    def __init__(self, checkpoint: Path):
        self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
        if self.device.type == 'cuda':
            torch.backends.cudnn.benchmark = True
        # torch.jit.load(path) uses a narrow Windows path internally.  Opening
        # the file in Python first keeps installations under Chinese paths safe.
        with checkpoint.open('rb') as stream:
            self.model = torch.jit.load(stream, map_location=self.device).eval()

    @torch.inference_mode()
    def run(self, task: dict, progress: Path, task_index: int, task_total: int):
        count = int(task['frames'])
        source_frames = load_frames(task['video'], count)
        atomic_json(progress, {'task': task_index + 1, 'tasks': task_total,
                               'message': f'A-roll {task_index + 1}/{task_total} · 检测人脸'})
        boxes = detect_faces(source_frames, Path(task['repo']), self.device.type,
                             int(task.get('face_batch_size', 16)))
        mels = mel_chunks(mel_spectrogram(task['audio']), count)
        batch_size = max(1, int(task.get('batch_size', 64)))
        total_batches = math.ceil(count / batch_size)
        output = Path(task['output'])
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_suffix('.part.mp4')
        height, width = source_frames[0].shape[:2]
        ffmpeg = subprocess.Popen([
            task['ffmpeg'], '-y', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'bgr24',
            '-video_size', f'{width}x{height}', '-framerate', str(FPS), '-i', '-', '-an',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart', str(partial)
        ], stdin=subprocess.PIPE)
        written = 0
        try:
            for batch_index, ((image_batch, mel_batch), originals, coordinates) in enumerate(
                    batches(source_frames, boxes, mels, batch_size)):
                image_tensor = torch.from_numpy(image_batch).float().to(self.device)
                mel_tensor = torch.from_numpy(mel_batch).float().to(self.device)
                predictions = self.model(mel_tensor, image_tensor).detach().cpu().numpy()
                predictions = predictions.transpose(0, 2, 3, 1) * 255.0
                for prediction, frame, (x1, y1, x2, y2) in zip(predictions, originals, coordinates):
                    patch = cv2.resize(prediction.astype(np.uint8), (x2 - x1, y2 - y1))
                    frame[y1:y2, x1:x2] = patch
                    ffmpeg.stdin.write(frame.tobytes())
                    written += 1
                atomic_json(progress, {'task': task_index + 1, 'tasks': task_total,
                                       'batch': batch_index + 1, 'batches': total_batches,
                                       'message': f'A-roll {task_index + 1}/{task_total} · 推理 '
                                                  f'{batch_index + 1}/{total_batches}'})
        finally:
            if ffmpeg.stdin:
                ffmpeg.stdin.close()
            code = ffmpeg.wait()
        if code or written != count:
            raise RuntimeError('Wav2Lip 没有生成完整视频')
        os.replace(partial, output)


def main(request_path: str):
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    progress = Path(request['progress'])
    atomic_json(progress, {'message': '正在加载 Wav2Lip 模型…'})
    engine = Engine(Path(request['checkpoint']))
    tasks = request['tasks']
    for index, task in enumerate(tasks):
        engine.run(task, progress, index, len(tasks))
    atomic_json(progress, {'task': len(tasks), 'tasks': len(tasks),
                           'message': 'Wav2Lip 推理完成'})


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        raise
