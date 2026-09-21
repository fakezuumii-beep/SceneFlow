"""Run one real LatentSync 1.6 SceneFlow project without touching user data."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', type=Path, required=True)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8189')
    parser.add_argument('--lips-expression', type=float, default=1.5)
    parser.add_argument('--steps', type=int, default=20)
    args = parser.parse_args()
    os.environ['SOLO_DATA_DIR'] = str(args.data_dir.resolve())
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    import core
    from providers.aroll import get_aroll_provider

    project = core.create_project('LatentSync 1.6 deployment smoke')
    folder = core.project_dir(project['id'])
    video = folder / 'assets' / ('host' + args.video.suffix.lower())
    audio = folder / 'assets' / ('audio' + args.audio.suffix.lower())
    shutil.copy2(args.video, video)
    shutil.copy2(args.audio, audio)
    duration = core.probe(audio)['duration']
    project.update(
        audio=audio.relative_to(folder).as_posix(),
        audio_name=args.audio.name,
        portrait=video.relative_to(folder).as_posix(),
        portrait_name=args.video.name,
        portrait_kind='video',
        portrait_duration=core.probe(video)['duration'],
        duration=duration,
        shots=[{
            'id': 'a1', 'kind': 'A', 'start': 0.0, 'end': duration,
            'title': 'LatentSync smoke', 'text': 'LatentSync smoke',
            'camera': 'medium', 'visual_change': 'hold', 'motion': None,
        }],
        arroll_provider_id='latentsync',
        arroll_provider_scope_version=1,
        job={'status': 'running', 'stage': 'LatentSync 生成', 'progress': 0, 'message': '准备真实推理'},
    )
    core.save_project(project)
    core.ACTIVE[project['id']] = {'cancel': False}
    provider = get_aroll_provider({
        'aroll_provider': 'latentsync',
        'aroll_latentsync_url': args.url,
        'aroll_latentsync_lips_expression': args.lips_expression,
        'aroll_latentsync_inference_steps': args.steps,
    })
    began = time.monotonic()
    try:
        provider.generate(project['id'])
    finally:
        core.ACTIVE.pop(project['id'], None)
    result = core.read_project(project['id'])
    shot = result['shots'][0]
    output = folder / shot['aroll_asset']
    probe = core.probe(output)
    print(json.dumps({
        'project_id': project['id'],
        'elapsed_seconds': round(time.monotonic() - began, 3),
        'output': str(output),
        'duration': probe['duration'],
        'streams': probe['streams'],
        'provenance': shot['aroll_provenance'],
        'ready': provider.is_ready(result, shot),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
