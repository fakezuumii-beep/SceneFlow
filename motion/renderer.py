"""Deterministic MP4 fallback renderer for the eight Motion templates."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PALETTE = {
    'paper': '#f8f6ed',
    'ink': '#18332d',
    'green': '#9fbd73',
    'amber': '#d8ad62',
    'blue': '#79a9be',
    'coral': '#cf8065',
    'rose': '#ae7e9d',
    'muted': '#71817a',
}


def _font(size, bold=False):
    candidates = (
        Path('C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc'),
        Path('C:/Windows/Fonts/msyh.ttc'),
        Path('C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf'),
    )
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _fit_lines(draw, text, font, max_width, max_lines=3):
    text = str(text or '').strip()
    if not text:
        return []
    lines, current = [], ''
    for char in text:
        candidate = current + char
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = char
            if len(lines) >= max_lines - 1:
                break
        else:
            current = candidate
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines


def _text(draw, xy, value, font, fill, max_width, max_lines=3, spacing=10):
    x, y = xy
    for line in _fit_lines(draw, value, font, max_width, max_lines):
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + spacing
    return y


def _base(draw, size, title, accent):
    width, height = size
    margin = round(min(width, height) * .065)
    draw.rounded_rectangle((margin, margin, margin + 82, margin + 10), radius=5, fill=accent)
    label_font = _font(max(18, round(height * .018)), True)
    draw.text((margin, margin + 30), 'SCENEFLOW / MOTION', font=label_font, fill=PALETTE['muted'])
    title_font = _font(max(42, round(height * (.058 if width > height else .046))), True)
    title_y = margin + 78
    title_y = _text(draw, (margin, title_y), title, title_font, PALETTE['ink'], width - margin * 2, 2, 8)
    draw.line((margin, title_y + 22, width - margin, title_y + 22), fill='#d8d7ca', width=3)
    return margin, title_y + 58


def _draw_title(draw, size, props):
    width, height = size
    _base(draw, size, props.get('title') or '重点信息', PALETTE['green'])
    title_font = _font(max(56, round(height * .085)), True)
    _text(draw, (round(width * .07), round(height * .30)), props.get('title'), title_font,
          PALETTE['ink'], round(width * .86), 4, 18)


def _draw_number(draw, size, props):
    width, height = size
    _base(draw, size, props.get('title') or '关键数据', PALETTE['coral'])
    number = (props.get('numbers') or [None])[0] or props.get('number') or '--'
    label = props.get('label') or ''
    number_font = _font(max(96, round(height * .16)), True)
    bbox = draw.textbbox((0, 0), str(number), font=number_font)
    x = (width - (bbox[2] - bbox[0])) // 2
    draw.text((x, round(height * .38)), str(number), font=number_font, fill=PALETTE['coral'])
    if label:
        label_font = _font(max(26, round(height * .034)))
        bbox = draw.textbbox((0, 0), str(label), font=label_font)
        draw.text(((width - (bbox[2] - bbox[0])) // 2, round(height * .61)),
                  str(label), font=label_font, fill=PALETTE['ink'])


def _draw_compare(draw, size, props):
    width, height = size
    margin, y = _base(draw, size, props.get('title') or '对比', PALETTE['blue'])
    values = props.get('items') or []
    left = props.get('left') or props.get('before') or (values[0] if values else 'A')
    right = props.get('right') or props.get('after') or (values[1] if len(values) > 1 else 'B')
    label = props.get('label') or ''
    gap = round(width * .045)
    box_width = round((width - margin * 2 - gap) / 2)
    box_height = round(height * .44)
    for index, (value, color) in enumerate(((left, PALETTE['blue']), (right, PALETTE['amber']))):
        x = margin + index * (box_width + gap)
        draw.rounded_rectangle((x, y, x + box_width, y + box_height), radius=22,
                               fill='#e7eef0' if index == 0 else '#f0e8d6')
        value_font = _font(max(46, round(height * .06)), True)
        _text(draw, (x + 30, y + 45), value, value_font, PALETTE['ink'], box_width - 60, 3, 8)
        draw.rectangle((x, y, x + 14, y + box_height), fill=color)
    if label:
        label_font = _font(max(24, round(height * .03)))
        draw.text((margin, y + box_height + 34), label, font=label_font, fill=PALETTE['muted'])


def _draw_list(draw, size, props):
    width, height = size
    margin, y = _base(draw, size, props.get('title') or '重点', PALETTE['green'])
    items = (props.get('items') or props.get('numbers') or [])[:5]
    row_height = max(70, round((height - y - margin) / max(1, len(items))))
    item_font = _font(max(30, round(height * .036)), True)
    for index, item in enumerate(items):
        top = y + index * row_height
        draw.ellipse((margin, top + 4, margin + 48, top + 52), fill=PALETTE['green'])
        number_font = _font(max(20, round(height * .023)), True)
        draw.text((margin + 16, top + 15), str(index + 1), font=number_font, fill='white')
        _text(draw, (margin + 72, top + 9), item, item_font, PALETTE['ink'], width - margin * 2 - 72, 2, 6)


def _draw_timeline(draw, size, props):
    width, height = size
    margin, y = _base(draw, size, props.get('title') or '时间线', PALETTE['amber'])
    items = (props.get('items') or props.get('numbers') or [])[:4]
    line_y = y + 75
    draw.line((margin + 25, line_y, width - margin - 25, line_y), fill='#cfc6ae', width=7)
    step = (width - margin * 2 - 70) / max(1, len(items) - 1) if len(items) > 1 else 0
    item_font = _font(max(24, round(height * .028)), True)
    for index, item in enumerate(items):
        x = margin + 34 + step * index
        draw.ellipse((x - 17, line_y - 17, x + 17, line_y + 17), fill=PALETTE['amber'])
        _text(draw, (x - 80, line_y + 45), item, item_font, PALETTE['ink'], 170, 3, 4)


def _draw_ranking(draw, size, props):
    width, height = size
    margin, y = _base(draw, size, props.get('title') or '排行', PALETTE['coral'])
    items = (props.get('items') or props.get('numbers') or [])[:5]
    row_height = max(65, round((height - y - margin) / max(1, len(items))))
    font = _font(max(28, round(height * .034)), True)
    for index, item in enumerate(items):
        top = y + index * row_height
        draw.rounded_rectangle((margin, top, width - margin, top + row_height - 12),
                               radius=12, fill='#f0e4df' if index == props.get('highlight_index', 0) else '#efede4')
        draw.text((margin + 22, top + 14), str(index + 1), font=font, fill=PALETTE['coral'])
        _text(draw, (margin + 90, top + 14), item, font, PALETTE['ink'], width - margin * 2 - 100, 2, 4)


def _draw_process(draw, size, props):
    width, height = size
    margin, y = _base(draw, size, props.get('title') or '流程', PALETTE['blue'])
    items = (props.get('items') or props.get('numbers') or [])[:3]
    item_font = _font(max(25, round(height * .03)), True)
    box_width = round((width - margin * 2 - 120) / max(1, len(items)))
    box_height = round(height * .32)
    for index, item in enumerate(items):
        x = margin + index * (box_width + 60)
        draw.rounded_rectangle((x, y, x + box_width, y + box_height), radius=18, fill='#e2edf0')
        _text(draw, (x + 24, y + 38), item, item_font, PALETTE['ink'], box_width - 48, 4, 8)
        if index < len(items) - 1:
            arrow_font = _font(max(36, round(height * .045)), True)
            draw.text((x + box_width + 13, y + box_height // 2 - 34), '>', font=arrow_font, fill=PALETTE['blue'])


def _draw_gallery(draw, size, props):
    width, height = size
    margin, y = _base(draw, size, props.get('title') or '项目', PALETTE['rose'])
    items = (props.get('items') or props.get('images') or [])[:6]
    columns = 1 if width < height else 3
    rows = max(1, math.ceil(len(items) / columns))
    gap = 18
    card_width = (width - margin * 2 - gap * (columns - 1)) // columns
    card_height = max(100, (height - y - margin - gap * (rows - 1)) // rows)
    colors = ('#ece1ed', '#e4ece0', '#f0e7d4', '#e2edf0', '#f0e4df', '#eee9da')
    font = _font(max(22, round(height * .027)), True)
    for index, item in enumerate(items):
        row, column = divmod(index, columns)
        left = margin + column * (card_width + gap)
        top = y + row * (card_height + gap)
        draw.rounded_rectangle((left, top, left + card_width, top + card_height),
                               radius=16, fill=colors[index % len(colors)])
        _text(draw, (left + 22, top + 25), item, font, PALETTE['ink'], card_width - 44, 4, 7)


DRAWERS = {
    'M_TITLE': _draw_title,
    'M_NUMBER': _draw_number,
    'M_COMPARE': _draw_compare,
    'M_LIST': _draw_list,
    'M_TIMELINE': _draw_timeline,
    'M_RANKING': _draw_ranking,
    'M_PROCESS': _draw_process,
    'M_GALLERY': _draw_gallery,
}


def render_motion_clip(shot, output_size, output_path):
    import core as c
    from visual_director.still_motion import stable_still_filter
    from .template_router import normalize_motion_style
    if normalize_motion_style(shot.get('motion_style')) == 'intel_board':
        from .intel_board import render_intel_board_clip
        return render_intel_board_clip(shot, output_size, output_path)
    template = str(shot.get('motion_type') or 'M_TITLE').upper()
    plan = shot.get('motion_plan') or {}
    props = dict(plan.get('props') or {})
    props.update(shot.get('motion_data') or {})
    props.setdefault('title', shot.get('title') or shot.get('visual_subject') or '')
    props.setdefault('items', shot.get('keywords') or [])
    props.setdefault('numbers', [])
    width, height = output_size
    scale = 2
    image = Image.new('RGB', (width * scale, height * scale), PALETTE['paper'])
    draw = ImageDraw.Draw(image)
    drawer = DRAWERS.get(template, _draw_title)
    drawer(draw, image.size, props)
    image = image.resize((width, height), Image.Resampling.LANCZOS)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    still = output_path.with_suffix('.png')
    image.save(still, quality=95)
    frames = max(1, round(max(.1, float(shot['end']) - float(shot['start'])) * 30))
    temporary = output_path.with_suffix('.part.mp4')
    filters = stable_still_filter(width, height, 30, .18)
    c.run([c.FFMPEG, '-y', '-v', 'error', '-loop', '1', '-i', still,
           '-vf', filters, '-frames:v', str(frames), '-an', '-c:v', 'libx264',
           '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p',
           '-threads', '4', '-movflags', '+faststart', temporary], timeout=1200)
    temporary.replace(output_path)
    return output_path, still


def motion_cache_key(shot, output_size):
    payload = {
        'shot': shot.get('id'), 'type': shot.get('motion_type'),
        'style': shot.get('motion_style'),
        'data': shot.get('motion_data'), 'plan': shot.get('motion_plan'),
        'start': shot.get('start'), 'end': shot.get('end'), 'size': output_size,
        'still_policy': 'static-hold-fade-v2',
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
