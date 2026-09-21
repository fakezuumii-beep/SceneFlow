"""Deterministic Edit Plan compiler for SceneFlow exports."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time

SCHEMA_VERSION = 'sceneflow-edit-plan-v2'


def _round(value):
    return round(float(value), 3)


def _overlap(start, end, other_start, other_end):
    return max(0.0, min(end, other_end) - max(start, other_start))


def plan_signature(project):
    payload = {
        'audio': project.get('audio'),
        'bgm': project.get('bgm'),
        'duration': project.get('duration'),
        'segments': project.get('segments') or [],
        'shots': [
            {key: shot.get(key) for key in (
                'id', 'kind', 'start', 'end', 'title', 'text', 'keywords',
                'camera', 'visual_change', 'asset', 'media_start',
                'aroll_asset', 'aroll_media_start',
            )}
            for shot in project.get('shots') or []
        ],
        'options': {
            key: (project.get('options') or {}).get(key)
            for key in (
                'auto_edit_remove_pauses', 'auto_edit_pause_threshold',
                'auto_edit_pause_padding', 'auto_edit_highlights',
                'auto_edit_cards',
                'bgm_enabled', 'bgm_volume',
            )
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


def _removals(duration, silences, options):
    if not options.get('auto_edit_remove_pauses', True):
        return []
    threshold = float(options.get('auto_edit_pause_threshold', .65))
    padding = float(options.get('auto_edit_pause_padding', .08))
    result = []
    for silence in sorted(silences or [], key=lambda item: float(item.get('start', 0))):
        raw_start = float(silence.get('start', 0))
        raw_end = float(silence.get('end', 0))
        if raw_end - raw_start < threshold:
            continue
        start = max(.04, raw_start + padding)
        end = min(duration - .04, raw_end - padding)
        if end - start < .04:
            continue
        if result and start <= result[-1]['end'] + .01:
            result[-1]['end'] = _round(max(end, result[-1]['end']))
        else:
            result.append({'start': _round(start), 'end': _round(end), 'reason': 'long_pause'})
    return result


def _keeps(duration, removals):
    keeps = []
    cursor = 0.0
    for removal in removals:
        start = float(removal['start'])
        end = float(removal['end'])
        if start - cursor >= .04:
            keeps.append({'source_start': _round(cursor), 'source_end': _round(start)})
        cursor = max(cursor, end)
    if duration - cursor >= .04:
        keeps.append({'source_start': _round(cursor), 'source_end': _round(duration)})
    if not keeps:
        keeps = [{'source_start': 0.0, 'source_end': _round(duration)}]
    output_cursor = 0.0
    for keep in keeps:
        keep['output_start'] = _round(output_cursor)
        output_cursor += keep['source_end'] - keep['source_start']
        keep['output_end'] = _round(output_cursor)
    return keeps


def _map_range(start, end, keeps, minimum=.02):
    mapped = []
    for keep in keeps:
        source_start = max(start, keep['source_start'])
        source_end = min(end, keep['source_end'])
        if source_end - source_start < minimum:
            continue
        output_start = keep['output_start'] + source_start - keep['source_start']
        mapped.append({
            'source_start': _round(source_start),
            'source_end': _round(source_end),
            'output_start': _round(output_start),
            'output_end': _round(output_start + source_end - source_start),
        })
    return mapped


def _visual_segments(project, keeps):
    result = []
    for shot in project.get('shots') or []:
        # A pause cut can leave a sub-frame sliver of the next shot inside the
        # preceding keep range. Dropping it would punch a hole in the visual
        # timeline, so the picture track keeps every positive fragment while
        # captions and cards stay on the wider anti-flicker threshold.
        for part, mapped in enumerate(
                _map_range(float(shot['start']), float(shot['end']), keeps, 1e-6), 1):
            result.append({
                'id': f'{shot["id"]}:{part}',
                'shot_id': shot['id'],
                'kind': shot['kind'],
                **mapped,
            })
    return result


def _keywords_for_range(project, start, end):
    ranked = []
    for shot in project.get('shots') or []:
        overlap = _overlap(start, end, float(shot['start']), float(shot['end']))
        if overlap <= 0:
            continue
        for word in shot.get('keywords') or []:
            text = str(word).strip()
            if 2 <= len(text) <= 18:
                ranked.append((overlap, text))
        subject = str(shot.get('visual_subject') or '').strip()
        if 2 <= len(subject) <= 18:
            ranked.append((overlap + .01, subject))
    result = []
    for _, word in sorted(ranked, key=lambda item: (-item[0], item[1])):
        if word not in result:
            result.append(word)
    return result[:2]


def _matching_highlights(text, candidates):
    """Map semantic keywords back to readable phrases that occur in a caption."""
    text = str(text or '')
    result = []
    for candidate in candidates:
        word = str(candidate or '').strip()
        if not word:
            continue
        match = word if word in text else ''
        if not match:
            fragments = re.findall(r'[\u3400-\u9fff]{2,}', word)
            choices = []
            for fragment in fragments:
                for size in range(min(8, len(fragment)), 1, -1):
                    matches = [
                        fragment[index:index + size]
                        for index in range(len(fragment) - size + 1)
                        if fragment[index:index + size] in text]
                    if matches:
                        choices.extend(matches)
                        break
            if choices:
                for phrase in sorted(
                        set(choices), key=lambda item: (-len(item), text.find(item))):
                    if phrase not in result:
                        result.append(phrase)
                    if len(result) >= 2:
                        return result
                continue
        if not match:
            for token in re.findall(r'[A-Za-z0-9][A-Za-z0-9.+#-]{2,}', word):
                found = re.search(re.escape(token), text, re.IGNORECASE)
                if found:
                    match = found.group(0)
                    break
        if match and match not in result:
            result.append(match)
        if len(result) >= 2:
            break
    return result


def _caption_events(project, keeps, highlights):
    result = []
    for caption in project.get('captions') or []:
        fragments = _map_range(float(caption['start']), float(caption['end']), keeps)
        if not fragments:
            continue
        # A removed pause is contiguous in output time, so a caption spanning
        # one is still a single readable line. Emitting one cue per fragment
        # repeated the whole text on both sides and flashed a 0.2 秒 sliver of
        # it before the real cue, which read as a stutter.
        source_start = fragments[0]['source_start']
        source_end = fragments[-1]['source_end']
        event = {
            'source_start': source_start,
            'source_end': source_end,
            'start': fragments[0]['output_start'],
            'end': fragments[-1]['output_end'],
            'text': str(caption.get('text') or ''),
        }
        if highlights:
            event['highlight'] = _matching_highlights(
                event['text'], _keywords_for_range(project, source_start, source_end))
        else:
            event['highlight'] = []
        result.append(event)
    return result


def _title_text(project):
    title = str(project.get('name') or '').strip()
    if title and len(title) >= 4 and not re.fullmatch(r'[A-Za-z_-]*\d+', title):
        return title[:80]
    narrative = project.get('narrative_segments') or []
    for semantic_type in ('intro', 'hook', 'summary'):
        item = next(
            (value for value in narrative
             if str(value.get('semantic_type') or '') == semantic_type
             and str(value.get('text') or '').strip()),
            None)
        if item:
            subject = re.sub(r'\s+', ' ', str(item.get('visual_subject') or '').strip())
            return (subject or re.sub(r'\s+', ' ', str(item['text']).strip()))[:32]
    return title[:80]


def _card_copy(item):
    text = re.sub(r'\s+', ' ', str(item.get('text') or '')).strip(' ，。；：')
    semantic_type = str(item.get('semantic_type') or '')
    subject = re.sub(r'\s+', ' ', str(item.get('visual_subject') or '')).strip(' ，。；：')
    if semantic_type == 'data':
        metric_match = re.search(
            r'(?:约|超过|不到|至少|最多|高达)?'
            r'(?:\d+(?:\.\d+)?|[零一二三四五六七八九十百千万亿两几]+)'
            r'(?:%|％|倍|秒|分钟|小时|天|周|月|年|万|亿)?',
            text)
        metric = metric_match.group(0) if metric_match else ''
        if subject and metric:
            return subject[:14] + '\n' + metric[:12], '关键数据'
        return (subject or text[:22]), '关键数据'
    if semantic_type == 'quote':
        quote = re.search(r'[“"]([^”"]{2,24})[”"]', text)
        return (quote.group(1) if quote else text[:24]), '原话'
    clause = re.split(r'[，,。；;]', text, maxsplit=1)[0]
    clause = re.sub(r'^(?:现代|真正|其实|因此|所以)', '', clause).strip()
    return (subject or clause or text)[:24], '核心观点'


def _card_events(project, keeps, enabled):
    if not enabled or not keeps:
        return []
    duration = keeps[-1]['output_end']
    cards = []
    title = _title_text(project)
    if title and duration >= .8:
        cards.append({
            'id': 'title-card',
            'type': 'title',
            'text': title[:80],
            'start': 0.12,
            'end': _round(min(duration, 3.2)),
            'position': 'top_left',
        })
    candidates = []
    for item in project.get('narrative_segments') or []:
        semantic_type = str(item.get('semantic_type') or '')
        if semantic_type not in ('data', 'quote', 'opinion'):
            continue
        mapped = _map_range(float(item['start']), float(item['end']), keeps)
        if not mapped:
            continue
        text = str(item.get('text') or '').strip()
        if not text:
            continue
        score = float(item.get('visual_value') or 0)
        if item.get('importance') == 'high':
            score += 2
        if semantic_type in ('data', 'quote'):
            score += 1
        display_text, label = _card_copy(item)
        candidates.append((
            score, mapped[0]['output_start'], display_text, label, semantic_type))
    last_end = cards[-1]['end'] if cards else 0
    selected = sorted(candidates, key=lambda item: (-item[0], item[1]))[:3]
    for index, (_, source_start, text, label, semantic_type) in enumerate(
            sorted(selected, key=lambda item: item[1]), 1):
        start = max(source_start, last_end + .35)
        if start - source_start > .75:
            continue
        end = min(duration, start + 3.5)
        if end - start < .8:
            continue
        cards.append({
            'id': f'insight-card-{index}',
            'type': 'insight',
            'semantic_type': semantic_type,
            'label': label,
            'text': text,
            'start': _round(start),
            'end': _round(end),
            'position': 'lower_third',
        })
        last_end = end
    return cards


def validate_edit_plan(plan):
    if not isinstance(plan, dict) or plan.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('精剪计划版本无效')
    duration = float(plan.get('source_duration') or 0)
    output_duration = float(plan.get('output_duration') or 0)
    if not math.isfinite(duration) or not math.isfinite(output_duration) or duration <= 0 or output_duration <= 0:
        raise ValueError('精剪计划时长无效')
    source_cursor = output_cursor = 0.0
    for keep in plan.get('keep_ranges') or []:
        values = [float(keep[key]) for key in ('source_start', 'source_end', 'output_start', 'output_end')]
        if not all(math.isfinite(value) for value in values):
            raise ValueError('精剪计划包含无效时间')
        source_start, source_end, output_start, output_end = values
        if source_start < source_cursor - .002 or abs(output_start - output_cursor) > .002:
            raise ValueError('精剪计划输出时间必须连续且有序')
        if source_end <= source_start or abs((source_end - source_start) - (output_end - output_start)) > .003:
            raise ValueError('精剪计划区间长度不一致')
        source_cursor = source_end
        output_cursor = output_end
    if abs(output_cursor - output_duration) > .003:
        raise ValueError('精剪计划总时长不一致')
    previous = 0.0
    for segment in plan.get('visual_segments') or []:
        if abs(float(segment['output_start']) - previous) > .003:
            raise ValueError('精剪画面时间线存在空隙或重叠')
        previous = float(segment['output_end'])
    if plan.get('visual_segments') and abs(previous - output_duration) > .003:
        raise ValueError('精剪画面未覆盖完整输出')
    for caption in plan.get('captions') or []:
        if not 0 <= float(caption['start']) < float(caption['end']) <= output_duration + .003:
            raise ValueError('精剪字幕超出输出范围')
    return plan


def build_edit_plan(project, silences):
    duration = float(project.get('duration') or 0)
    if duration <= 0 or not project.get('audio'):
        raise ValueError('请先准备音频，再生成自动精剪计划')
    if not project.get('shots'):
        raise ValueError('请先生成分镜，再生成自动精剪计划')
    options = project.get('options') or {}
    removals = _removals(duration, silences, options)
    keeps = _keeps(duration, removals)
    output_duration = keeps[-1]['output_end']
    plan = {
        'schema_version': SCHEMA_VERSION,
        'source_signature': plan_signature(project),
        'created_at': time.time(),
        'source_duration': _round(duration),
        'output_duration': _round(output_duration),
        'removed_seconds': _round(duration - output_duration),
        'remove_ranges': removals,
        'keep_ranges': keeps,
        'visual_segments': _visual_segments(project, keeps),
        'captions': _caption_events(
            project, keeps, bool(options.get('auto_edit_highlights', True))),
        'overlays': _card_events(
            project, keeps, bool(options.get('auto_edit_cards', True))),
        'audio': {
            'bgm_asset': project.get('bgm') if options.get('bgm_enabled') else None,
            'bgm_volume': float(options.get('bgm_volume', .14)),
            'ducking': bool(project.get('bgm') and options.get('bgm_enabled')),
        },
        'style': {
            'subtitle': 'sceneflow-highlight-v1',
            'cards': 'sceneflow-editorial-v2',
        },
    }
    return validate_edit_plan(plan)


def plan_is_current(project):
    plan = project.get('edit_plan')
    return bool(
        plan and plan.get('schema_version') == SCHEMA_VERSION
        and plan.get('source_signature') == plan_signature(project))
