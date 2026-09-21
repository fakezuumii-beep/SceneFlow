"""MiniMax H3 generated-scene resolver.

This module reuses the existing AutoDL H3 engine, queue, task persistence,
polling, download, and provider configuration.  Only the prompt builder and
shot-selection rules are separate from A-roll.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from providers.aroll import autodl_h3


VIDEO_PROMPT_SUFFIX = (
    '【禁止项】 文字/UI/水印/Logo/角标/可读文字/真实UI '
    '【强制声明】 无背景音乐,仅保留环境音与人声和音效;'
    '画面禁字幕/文字/水印/Logo;禁止可读文字(指画面字幕文字,不含人声台词)。'
)


class H3Engine:
    """Original multi-reference H3 facade over the shared AutoDL transport."""

    @staticmethod
    def collect(provider, pid, cache, body, index, total):
        return autodl_h3._collect(
            provider, pid, cache, body, index, total,
            stage='MiniMax H3 多参生成',
        )

    @staticmethod
    def normalize(raw, target, frames, size):
        return autodl_h3._normalize(raw, target, frames, size)


class GenericH3Provider:
    id = 'autodl_h3_multiref'
    name = 'MiniMax H3 原始多参生成'
    short_name = 'H3 · 多参'
    runtime = 'online'
    version = 'autodl-h3-multiref-v1'

    def __init__(self, settings):
        self.settings = settings


class GeneratedScenePromptBuilder:
    def build(self, shot, reference_count=0):
        concept = str(
            shot.get('generation_prompt')
            or shot.get('generation_concept')
            or shot.get('visual_subject')
            or shot.get('text')
            or ''
        ).strip()
        continuity = str(shot.get('continuity_group') or '').strip()
        lines = [
            '生成一个用于新闻或知识视频的写实场景镜头，不出现主播口播。',
            f'内容目标：{concept}',
            '画面自然、真实、电影感，动作连贯，主体明确，环境细节符合现实。',
            '不要字幕，不要文字水印，不要UI界面文字，不要人物对着镜头说话，不要口型特写。',
            '不要演播室，不要播客麦克风，不要延续主持人身份。',
            '镜头必须稳定：固定机位或极轻微的稳定主体运动，不做推拉、变焦、机械横移或快速运镜。',
        ]
        if continuity:
            lines.append(f'保持 continuity_group={continuity} 内已建立的环境、人物和视觉风格连续。')
        else:
            lines.append('不要继承上一镜头的参考图或人物身份，除非参考图就是本镜头的生成起点。')
        lines.append(
            f'参考模式：Ref2VA。当前提供 {max(0, int(reference_count))} 张参考图；'
            '图片承担内容、布局和风格主参考，不是必须逐像素保持的首帧。'
        )
        lines.append(VIDEO_PROMPT_SUFFIX)
        return '\n'.join(lines)


def _inside_project(project, relative):
    import core as c
    value = str(relative or '').strip()
    if not value:
        return None
    try:
        return c.asset_path(project['id'], value)
    except (ValueError, OSError):
        return None


def _first_frame(source, target):
    import core as c
    suffix = Path(source).suffix.lower()
    if suffix in ('.png', '.jpg', '.jpeg', '.webp'):
        shutil.copy2(source, target)
        return target
    c.run([c.FFMPEG, '-y', '-v', 'error', '-i', source, '-frames:v', '1', target], timeout=120)
    return target


def _color_guide(target, size):
    width, height = size
    width = max(512, round(width / 2))
    height = max(512, round(height / 2))
    image = Image.new('RGB', (width, height), '#7799a8')
    draw = ImageDraw.Draw(image)
    horizon = round(height * .62)
    draw.rectangle((0, horizon, width, height), fill='#354f4a')
    draw.ellipse((round(width * .58), round(height * .08), round(width * .88), round(height * .36)),
                 fill='#e2c587')
    for index in range(9):
        x = round(width * index / 8)
        draw.rectangle((x, horizon - 180 + index * 12, x + 42, horizon + 10), fill='#60777b')
    image = image.filter(ImageFilter.GaussianBlur(2))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, quality=95)
    return target


class GeneratedSceneResolver:
    def __init__(self, prompt_builder=None, engine=None):
        self.prompt_builder = prompt_builder or GeneratedScenePromptBuilder()
        self.engine = engine or H3Engine()

    def resolve(self, settings, project, shot):
        import core as c

        token = str(settings.get('aroll_autodl_api_key') or '').strip()
        if len(token) < 12 or '*' in token:
            raise ValueError('G 类 MiniMax H3 多参生成需要完整的 AutoDL ComfyUI Token')
        resolution = str(settings.get('aroll_autodl_resolution') or '768p横')
        if resolution not in autodl_h3.RESOLUTIONS:
            raise ValueError('G 类 MiniMax H3 分辨率无效')
        provider = GenericH3Provider(settings)
        folder = c.project_dir(project['id'])
        cache_root = folder / 'cache' / 'generated'
        cache_root.mkdir(parents=True, exist_ok=True)
        real_duration = max(.1, float(shot['end']) - float(shot['start']))
        api_duration = max(3, min(autodl_h3.MAX_SECONDS, math.ceil(real_duration - 1e-9)))
        target_duration = min(real_duration, float(api_duration))
        cloud_resolution = autodl_h3.CLOUD_RESOLUTION[resolution]
        output_size = autodl_h3.RESOLUTIONS[resolution]
        frames = max(1, round(target_duration * autodl_h3.FPS))
        signature = hashlib.sha256(json.dumps({
            'shot': shot.get('id'),
            'prompt_source': (
                shot.get('generation_prompt')
                or shot.get('generation_concept')
                or shot.get('visual_subject')
                or shot.get('text')
            ),
            'reference': shot.get('reference_image'),
            'references': shot.get('reference_images') or [],
            'reference_audios': shot.get('reference_audios') or [],
            'continuity': shot.get('continuity_group'),
            'duration': api_duration, 'resolution': resolution,
            'prompt_policy': 'h3-multiref-static-ref2va-v2',
        }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
        cache = cache_root / signature
        cache.mkdir(parents=True, exist_ok=True)

        audio = cache / 'audio.wav'
        autodl_h3._audio_chunk(project, float(shot['start']), target_duration,
                               float(api_duration), audio)
        references = []
        for value in shot.get('reference_images') or []:
            path = _inside_project(project, value)
            if path and path not in references:
                references.append(path)
        explicit = _inside_project(project, shot.get('reference_image'))
        if explicit and explicit not in references:
            references.insert(0, explicit)
        reference_mode = 'multi_reference' if references else 'generated_scene_guide'
        if not references and shot.get('continuity_group'):
            current = c.read_project(project['id'])
            index = next((i for i, item in enumerate(current['shots']) if item['id'] == shot['id']), None)
            previous = current['shots'][index - 1] if index is not None and index > 0 else None
            if (previous and previous.get('visual_role') == 'G'
                    and previous.get('continuity_group') == shot.get('continuity_group')):
                source = previous.get('asset') or previous.get('aroll_asset')
                if source:
                    path = _inside_project(current, source)
                    if path is not None:
                        references.append(path)
                        reference_mode = 'continuity_group'
        guide = cache / 'reference-guide.png'
        if not references:
            references = [_color_guide(guide, output_size)]
        prepared_references = []
        for index, reference in enumerate(references[:9], 1):
            target = cache / f'reference-{index}{reference.suffix.lower()}'
            if reference != target:
                target = _first_frame(reference, target)
            if target not in prepared_references:
                prepared_references.append(target)
        prompt = self.prompt_builder.build(shot,len(prepared_references))

        body = {
            'prompt': prompt,
            'resolution': cloud_resolution,
            'duration': api_duration,
            'seed': int(shot.get('generation_seed') or (int(signature[:12], 16) % 999_999_999_999_999) + 1),
            'ref_audio_0': autodl_h3._data_url(audio, 'audio/wav'),
        }
        for index, value in enumerate((shot.get('reference_audios') or [])[:2], 1):
            reference_audio = _inside_project(project, value)
            if reference_audio is not None:
                body[f'ref_audio_{index}'] = autodl_h3._data_url(reference_audio)
        for index, reference in enumerate(prepared_references):
            body[f'ref_image_{index}'] = autodl_h3._data_url(reference)
        acquired = False
        try:
            while not acquired:
                if c.ACTIVE.get(project['id'], {}).get('cancel'):
                    raise RuntimeError('已停止；尚未提交新的 AutoDL 付费任务')
                acquired = autodl_h3.GLOBAL_TASK_SLOTS.acquire(timeout=.5)
            raw = self.engine.collect(provider, project['id'], cache, body, 0, 1)
            normalized = cache / 'normalized.mp4'
            self.engine.normalize(raw, normalized, frames, output_size)
        finally:
            if acquired:
                autodl_h3.GLOBAL_TASK_SLOTS.release()

        assets = folder / 'assets'
        final = assets / f'generated-h3-{signature}.mp4'
        if not final.exists():
            shutil.copy2(normalized, final)
        state = autodl_h3._json(cache / 'task.json')
        return {
            'asset_type': 'video',
            'asset_path': final.relative_to(folder).as_posix(),
            'duration': round(frames / autodl_h3.FPS, 3),
            'source': 'MiniMax H3 generated scene',
            'metadata': {
                'resolver': 'generated_scene',
                'provider': 'autodl_h3',
                'model': 'MiniMax H3',
                'workflow_id': autodl_h3.WORKFLOW_ID,
                'adapter_id': 'autodl_h3_image_audio_to_video',
                'prompt': prompt,
                'seed': body['seed'],
                'task_id': state.get('task_id'),
                'duration_requested': api_duration,
                'duration_used': round(frames / autodl_h3.FPS, 3),
                'resolution': resolution,
                'reference_images': [
                    str(reference.relative_to(folder)).replace('\\', '/')
                    if reference.is_relative_to(folder) else str(reference)
                    for reference in prepared_references
                ],
                'reference_audios': [
                    str(value) for value in (shot.get('reference_audios') or [])[:2]
                ],
                'reference_policy': reference_mode,
                'reference_mode': 'Ref2VA',
                'continuity_group': shot.get('continuity_group'),
                'generated_at': time.time(),
            },
            'status': 'ready',
        }


def generate_scene(settings, project, shot):
    return GeneratedSceneResolver().resolve(settings, project, shot)
