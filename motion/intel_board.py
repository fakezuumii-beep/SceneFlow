"""Animated intel-board motion templates (情报板式).

The static-still templates in ``motion.renderer`` hold one PNG under a fade
filter. These boards are drawn frame by frame so the reference mechanisms
survive: evidence accumulation, jitter-to-settle numbers, a single continuous
draw-on curve, inward-closing accent frames, and a hold-stable ending.

Props contract (all optional, degrade gracefully):
    eyebrow    {"left": str, "center": str, "right": str}
    title      headline; ``|`` breaks a line, ``*word*`` marks the red accent
    subtitle   one muted line under the headline
    numbers    [{"value","label","accent","jitter":[lo,hi],"suffix"}]
    items      accumulated rows for the list/gallery layouts
    tags       small boxed labels pinned bottom-right
    footnote   boxed red accent label; footnote_note adds a muted aside
    columns    [{"heading","body","callouts":[...]}] for the compare layout
    axis       "columns" | "stacked"
    accent_side  which compare panel receives the red frame
    grid       [rows, columns]; filled lists the solid matrix cells
    range      {"start","end","ticks":[...],"arrow"}
    boxes      [{"text"}] nodes for the process layout
    influence  [{"text","direction"}]
    meta       muted aside pinned right of a list layout
    strike     title line index to cross out
"""
from __future__ import annotations

import math
import random
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


PAPER = (233, 232, 227)
INK = (24, 24, 24)
MUTED = (128, 126, 122)
HAIRLINE = (40, 40, 40)
RED = (208, 32, 32)

FPS = 30
MAX_FRAMES = 1800
MARGIN_RATIO = 0.073
DEFAULT_BUILD_SECONDS = 8.0
MIN_BUILD_SECONDS = 6.0
MAX_BUILD_SECONDS = 14.0

FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"
FONT_REG = "C:/Windows/Fonts/msyh.ttc"
FONT_FALLBACK = ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf")

# One causal chain shared by every board; only the duration differs.
S_EYEBROW = (0.030, 0.115)
S_RULE = (0.060, 0.150)
S_TITLE = (0.120, 0.275)
S_SUBTITLE = (0.275, 0.345)
S_GRAPHIC = (0.345, 0.520)
S_DATA = (0.480, 0.760)
S_ACCENT = (0.690, 0.810)
S_CLOSE = (0.760, 0.870)


def _font(size, bold=False):
    candidates = (FONT_BOLD if bold else FONT_REG, FONT_REG) + (
        FONT_FALLBACK if not bold else FONT_FALLBACK[:1]
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, int(size))
        except OSError:
            continue
    return ImageFont.load_default()


def ease_out(t):
    t = max(0.0, min(1.0, float(t)))
    return 1 - (1 - t) ** 3


def segment(t, start, end):
    if end <= start:
        return 1.0
    return max(0.0, min(1.0, (float(t) - start) / (end - start)))


def phase(t, window):
    return ease_out(segment(t, window[0], window[1]))


def draw_polyline_progress(draw, points, progress, fill, width):
    """Draw a polyline only as far as ``progress`` of its total length."""
    if progress <= 0 or len(points) < 2:
        return
    pairs = list(zip(points, points[1:]))
    lengths = [math.dist(a, b) for a, b in pairs]
    total = sum(lengths)
    if total <= 0:
        return
    target = total * min(1.0, progress)
    walked = 0.0
    for (a, b), span in zip(pairs, lengths):
        if walked >= target:
            break
        remain = target - walked
        if remain >= span or span == 0:
            draw.line([a, b], fill=fill, width=width)
        else:
            ratio = remain / span
            draw.line([a, (a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio)],
                      fill=fill, width=width)
        walked += span


def iso_box(cx, cy, w, h):
    dy = w * 0.5
    tl, tb, tr, tt = (cx - w, cy), (cx, cy + dy), (cx + w, cy), (cx, cy - dy)
    dl, db, dr = (tl[0], tl[1] + h), (tb[0], tb[1] + h), (tr[0], tr[1] + h)
    return [[tl, tb, tr, tt, tl], [tl, dl], [tb, db], [tr, dr], [dl, db, dr]]


def iso_monitor(cx, cy, w, h):
    dy = w * 0.5
    return [
        [(cx - w, cy), (cx, cy + dy), (cx + w, cy), (cx, cy - dy), (cx - w, cy)],
        [(cx, cy + dy), (cx, cy + dy + h)],
    ]


def text_alpha(layer, xy, value, fnt, fill, anchor=None, alpha=1.0):
    alpha = max(0.0, min(1.0, float(alpha)))
    if alpha <= 0.01 or not str(value or ""):
        return
    tmp = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    ImageDraw.Draw(tmp).text(
        xy, str(value), font=fnt, fill=tuple(fill)[:3] + (int(255 * alpha),), anchor=anchor
    )
    layer.alpha_composite(tmp)


def text_width(draw, value, fnt):
    return draw.textlength(str(value or ""), font=fnt)


def wrap_text(draw, value, fnt, max_width, max_lines=3):
    """Greedy wrap for CJK-heavy copy that also breaks on latin spaces."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    lines, current = [], ""
    for char in text:
        if current and text_width(draw, current + char, fnt) > max_width:
            lines.append(current)
            current = char
            if len(lines) >= max_lines:
                break
        else:
            current += char
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines:
        lines[-1] = lines[-1][: max(1, len(lines[-1]) - 1)] + "…"
    return lines


def draw_wrapped(layer, draw, xy, value, fnt, fill, max_width, max_lines=3,
                 spacing=1.35, alpha=1.0):
    x, y = xy
    lines = wrap_text(draw, value, fnt, max_width, max_lines)
    for index, line in enumerate(lines):
        text_alpha(layer, (x, y + index * round(fnt.size * spacing)), line, fnt, fill, alpha=alpha)
    return y + len(lines) * round(fnt.size * spacing)


_TITLE_PATTERN = re.compile(r"\*(.+?)\*")


def parse_title(value):
    """Split a headline into lines of ``(text, accent)`` runs."""
    lines = []
    for raw_line in str(value or "").split("|"):
        runs, cursor = [], 0
        for match in _TITLE_PATTERN.finditer(raw_line):
            if match.start() > cursor:
                runs.append((raw_line[cursor:match.start()], False))
            runs.append((match.group(1), True))
            cursor = match.end()
        if cursor < len(raw_line):
            runs.append((raw_line[cursor:], False))
        lines.append([run for run in runs if run[0]])
    return [line for line in lines if line] or [[("重点信息", False)]]


def runs_width(draw, runs, fnt):
    return sum(text_width(draw, text, fnt) for text, _ in runs)


def draw_runs(layer, xy, runs, fnt, alpha):
    x, y = xy
    draw = ImageDraw.Draw(layer)
    for text, is_accent in runs:
        text_alpha(layer, (x, y), text, fnt, RED if is_accent else INK, alpha=alpha)
        x += text_width(draw, text, fnt)
    return x


def make_paper(width, height):
    """Paper field: flat tone, fine fibre noise, soft vignette."""
    base = Image.new("RGB", (width, height), PAPER)
    noise = Image.effect_noise((width, height), 14).convert("L")
    noise = noise.filter(ImageFilter.GaussianBlur(0.6))
    base = Image.blend(base, Image.merge("RGB", (noise, noise, noise)), 0.055)
    vignette = Image.new("L", (width, height), 0)
    vd = ImageDraw.Draw(vignette)
    steps = 90
    edge = min(width, height)
    band = max(1, round(edge * 0.45 / steps))
    for i in range(steps):
        inset = i * band
        if inset * 2 >= edge:
            break
        vd.rectangle((inset, inset, width - inset, height - inset),
                     outline=int(24 * (i / steps) ** 2.1))
    vignette = vignette.filter(
        ImageFilter.GaussianBlur(max(8, round(min(width, height) * 0.035)))
    )
    return Image.composite(Image.new("RGB", (width, height), (150, 148, 143)), base, vignette)


def _number_specs(values):
    """Accept the generic string list and the intel-board spec list alike."""
    specs = []
    for value in values or []:
        if isinstance(value, dict):
            if value:
                specs.append(value)
        elif value not in (None, ""):
            specs.append({"value": str(value)})
    return specs


def _heading_body(value, limit=14):
    """'不设强制标准：头部自主权更大' -> ('不设强制标准', '头部自主权更大')."""
    text = str(value or "").strip()
    for mark in ("：", ":"):
        head, separator, tail = text.partition(mark)
        if separator and head.strip() and tail.strip():
            return head.strip()[:limit], tail.strip()
    return text[:limit], text


def _compare_columns(props):
    columns = [c for c in (props.get("columns") or []) if isinstance(c, dict) and c]
    if len(columns) >= 2:
        return columns[:2]
    items = [str(v).strip() for v in (props.get("items") or []) if str(v).strip()]
    left = str(props.get("before") or props.get("left") or (items[0] if items else "")).strip()
    right = str(props.get("after") or props.get("right") or (items[1] if len(items) > 1 else "")).strip()
    if not left and not right:
        return []
    result = []
    for value in (left, right):
        heading, body = _heading_body(value)
        result.append({"heading": heading or "对比", "body": body})
    return result


def normalize_props(props):
    """Adapt the generic scene_flow prop contract to the intel-board layouts.

    ``motion.template_router.build_motion_plan`` emits the scene_flow prop set
    (``items`` / ``numbers`` / ``before`` / ``after`` / ``images``), while these
    layouts read their own keys (``columns`` / ``boxes`` / ``range``). Without
    this adapter an M_COMPARE shot renders as a title on an otherwise empty
    board, and a plain-string ``numbers`` list raises AttributeError.
    """
    result = dict(props or {})
    template = str(result.get("template") or "").upper()
    result["numbers"] = _number_specs(result.get("numbers"))
    if not isinstance(result.get("eyebrow"), dict):
        result["eyebrow"] = {
            "left": str(result.get("eyebrow_left") or "").strip(),
            "center": str(result.get("eyebrow_center") or "").strip(),
            "right": str(result.get("label") or "").strip(),
        }
    if not result.get("tags") and result.get("images"):
        result["tags"] = [str(v).strip() for v in result["images"] if str(v).strip()][:4]
    items = [str(v).strip() for v in (result.get("items") or []) if str(v).strip()]
    if template == "M_COMPARE":
        result["columns"] = _compare_columns(result)
        result.setdefault("axis", "columns")
        result.setdefault("accent_side", 1)
    elif template == "M_PROCESS" and not result.get("boxes"):
        result["boxes"] = [{"text": value[:22]} for value in items[:3]]
    return result


class Board:
    """Geometry and drawing helpers for one board frame."""

    def __init__(self, width, height, props):
        self.width = width
        self.height = height
        self.props = normalize_props(props)
        # Wall-clock seconds this board occupies. When it is longer than the
        # build window the layout finishes early and holds the settled frame,
        # which is how a board can carry a long stretch of narration.
        try:
            self.duration = max(0.1, float(self.props.get("duration") or 0))
        except (TypeError, ValueError):
            self.duration = 0.0
        # Seconds of this board already shown by earlier parts of the same
        # segment, so a split board keeps building instead of restarting.
        try:
            self.offset = max(0.0, float(self.props.get("build_offset") or 0))
        except (TypeError, ValueError):
            self.offset = 0.0
        self.margin = round(min(width, height) * MARGIN_RATIO)
        self.unit = min(width, height)
        self.inner = width - self.margin * 2
        self.hair = max(1, round(self.unit * 0.0022))

    def build_progress(self, t):
        """Compress the build into ``build_seconds``, then hold stable."""
        try:
            build = float(self.props.get("build_seconds") or 0)
        except (TypeError, ValueError):
            build = 0.0
        if not build:
            build = DEFAULT_BUILD_SECONDS
        # ``duration`` is clamped to a floor for the layout maths, so read the
        # declared value here: a board that never declared one is driven by
        # normalised progress, and a split part resumes the whole board clock.
        try:
            declared = max(0.0, float(self.props.get("duration") or 0))
        except (TypeError, ValueError):
            declared = 0.0
        if declared > 0 and build > 0:
            return min(1.0, (self.offset + float(t) * self.duration) / build)
        return float(t)

    # -- shared chrome -------------------------------------------------
    def eyebrow(self, layer, draw, t):
        bar = phase(t, S_EYEBROW)
        data = self.props.get("eyebrow") or {}
        fnt = _font(max(16, round(self.unit * 0.030)))
        top = round(self.height * 0.048)
        for value, xy, anchor in (
            (data.get("left"), (self.margin, top), None),
            (data.get("center"), (self.width // 2, top), "ma"),
            (data.get("right"), (self.width - self.margin, top), "ra"),
        ):
            if value:
                text_alpha(layer, xy, value, fnt, MUTED, anchor=anchor, alpha=bar)

    def rule(self, layer, draw, y, t, window=None):
        p = phase(t, window or S_RULE)
        draw_polyline_progress(
            draw, [(self.margin, y), (self.width - self.margin, y)],
            p, tuple(HAIRLINE) + (230,), self.hair,
        )
        return y

    def headline(self, layer, draw, top, t, size=None):
        p = phase(t, S_TITLE)
        lines = parse_title(self.props.get("title"))
        fnt = _font(size or max(34, round(self.unit * 0.125)), bold=True)
        step = round(fnt.size * 1.22)
        y = top + (1 - p) * round(fnt.size * 0.42)
        strike = self.props.get("strike")
        for index, runs in enumerate(lines):
            while runs_width(draw, runs, fnt) > self.inner and fnt.size > 20:
                fnt = _font(fnt.size - 4, bold=True)
                step = round(fnt.size * 1.22)
            draw_runs(layer, (self.margin, y), runs, fnt, p)
            if strike is not None and index == int(strike):
                p_strike = phase(t, (S_TITLE[1], S_TITLE[1] + 0.06))
                if p_strike > 0:
                    line_w = runs_width(draw, runs, fnt) * p_strike
                    y_line = y + round(fnt.size * 0.60)
                    lift = round(fnt.size * 0.05)
                    draw.line([(self.margin, y_line + lift), (self.margin + line_w, y_line - lift)],
                              fill=tuple(HAIRLINE) + (240,),
                              width=max(2, round(self.unit * 0.0032)))
            y += step
        return y

    def subtitle(self, layer, t, y):
        value = self.props.get("subtitle")
        if not value:
            return y
        p = phase(t, S_SUBTITLE)
        fnt = _font(max(16, round(self.unit * 0.034)))
        text_alpha(layer, (self.margin, y + (1 - p) * round(fnt.size * 0.5)),
                   value, fnt, MUTED, alpha=p)
        return y + round(fnt.size * 1.7)

    def tags(self, layer, draw, t, y=None):
        items = [str(v) for v in (self.props.get("tags") or [])][:4]
        if not items:
            return
        fnt = _font(max(14, round(self.unit * 0.026)))
        widths = [text_width(draw, v, fnt) for v in items]
        pad, gap = round(fnt.size * 0.9), round(fnt.size * 1.5)
        total = sum(widths) + pad * 2 * len(items) + gap * (len(items) - 1)
        row_h = round(fnt.size * 1.9)
        x = self.width - self.margin - total
        y = y if y is not None else self.height - self.margin - row_h
        for index, (value, tw) in enumerate(zip(items, widths)):
            p = phase(t, (S_CLOSE[0] + index * 0.03, S_CLOSE[0] + 0.05 + index * 0.03))
            if p <= 0:
                continue
            box_y = y + (1 - p) * round(fnt.size * 0.4)
            draw.rectangle([x, box_y, x + tw + pad * 2, box_y + row_h],
                           outline=tuple(HAIRLINE) + (int(220 * p),), width=max(1, self.hair))
            text_alpha(layer, (x + pad, box_y + round(fnt.size * 0.42)), value, fnt,
                       (70, 70, 70), alpha=p)
            x += tw + pad * 2 + gap

    def footnote(self, layer, draw, t, y=None):
        value = self.props.get("footnote")
        if not value:
            return
        p = phase(t, S_ACCENT)
        fnt = _font(max(14, round(self.unit * 0.028)))
        pad = round(fnt.size * 0.85)
        tw = text_width(draw, value, fnt)
        x = self.margin
        row_y = y if y is not None else self.height - self.margin - round(fnt.size * 2)
        draw.rectangle([x, row_y, x + tw + pad * 2, row_y + round(fnt.size * 1.9)],
                       outline=tuple(RED) + (int(220 * p),), width=max(1, self.hair))
        text_alpha(layer, (x + pad, row_y + round(fnt.size * 0.42)), value, fnt, RED, alpha=p)
        note = self.props.get("footnote_note")
        if note:
            text_alpha(layer, (x + tw + pad * 3, row_y + round(fnt.size * 0.42)), note, fnt,
                       MUTED, alpha=p)

    # -- data layers ---------------------------------------------------
    def numbers(self, layer, draw, t, y):
        specs = [s for s in (self.props.get("numbers") or []) if s][:3]
        if not specs:
            return y
        col = self.inner / len(specs)
        f_num = _font(max(34, round(self.unit * 0.185)), bold=True)
        # Three numbers at full size collide on narrow canvases; shrink the
        # numeral face until the widest value fits its own column.
        available = col * 0.90
        while f_num.size > 28:
            widest = max(
                text_width(draw, str(spec.get("value") or "--"), f_num) for spec in specs
            )
            if widest <= available:
                break
            f_num = _font(f_num.size - 4, bold=True)
        f_lab = _font(max(14, round(self.unit * 0.028)))
        rng = random.Random(7)
        span = (S_DATA[1] - S_DATA[0]) / len(specs)
        for index, spec in enumerate(specs):
            t0 = S_DATA[0] + span * index
            t1 = t0 + span * 0.92
            p = segment(t, t0, t1)
            if p <= 0:
                continue
            value = str(spec.get("value") or "--")
            if p < 1:
                low, high = (list(spec.get("jitter") or [None, None]) + [None, None])[:2]
                if low is not None and high is not None:
                    digits = re.sub(r"[^0-9.]", "", value) or "0"
                    suffix = value[len(digits):] or str(spec.get("suffix") or "")
                    value = f"{rng.randint(int(low), int(high))}{suffix}"
            x = self.margin + col * index
            appear = ease_out(segment(t, t0, t0 + 0.05))
            text_alpha(layer, (x, y + (1 - appear) * round(f_num.size * 0.28)),
                       value, f_num, INK, alpha=appear)
            if spec.get("label"):
                text_alpha(layer, (x, y + round(f_num.size * 1.42)), spec["label"], f_lab, MUTED,
                           alpha=ease_out(segment(t, t0 + 0.03, t1)))
            if spec.get("accent") and p >= 1:
                box_p = ease_out(segment(t, t1, t1 + 0.06))
                if box_p > 0:
                    tw = text_width(draw, value, f_num)
                    box_w = tw + round(f_num.size * 0.34) * box_p
                    box_h = round(f_num.size * 1.30)
                    top = y - round(f_num.size * 0.14)
                    cx = x + tw / 2
                    draw.rectangle([cx - box_w / 2, top, cx + box_w / 2, top + box_h],
                                   outline=tuple(RED) + (int(225 * box_p),),
                                   width=max(1, round(self.unit * 0.0024)))
        return y

    def list_rows(self, layer, draw, t, y, items, meta=None, bullet=False):
        rows = [str(v) for v in (items or [])][:6]
        if not rows:
            return y
        fnt = _font(max(18, round(self.unit * 0.038)))
        row_h = round(fnt.size * 2.4)
        axis_x = self.margin + round(self.unit * 0.012)
        axis = phase(t, S_GRAPHIC)
        draw_polyline_progress(draw, [(axis_x, y + row_h * len(rows)), (axis_x, y - row_h * 0.35)],
                               axis, tuple(HAIRLINE) + (235,), self.hair)
        if axis >= 1:
            dot = ease_out(segment(t, S_GRAPHIC[0] + 0.08, S_GRAPHIC[0] + 0.13))
            r = round(self.unit * 0.011 * dot)
            if r > 0:
                cy = y - row_h * 0.35
                draw.ellipse([axis_x - r, cy - r, axis_x + r, cy + r],
                             fill=tuple(RED) + (int(235 * dot),))
        right = self.width - self.margin - (round(self.unit * 0.26) if meta else 0)
        for index, row in enumerate(rows):
            start = S_DATA[0] + index * 0.045
            p = ease_out(segment(t, start, start + 0.05))
            if p <= 0:
                continue
            top = y + index * row_h
            draw.rectangle([axis_x + round(self.unit * 0.03), top, right,
                            top + round(fnt.size * 1.62)],
                           outline=tuple(HAIRLINE) + (int(225 * p),), width=max(1, self.hair))
            text_alpha(layer, (axis_x + round(self.unit * 0.055), top + round(fnt.size * 0.42)),
                       row, fnt, INK, alpha=p)
            if bullet and index < 3:
                bx = axis_x + round(self.unit * 0.008)
                d = round(self.unit * 0.010)
                draw.ellipse([bx, top + round(fnt.size * 0.60), bx + d, top + round(fnt.size * 0.60) + d],
                             fill=tuple(RED) + (int(235 * p),))
        if meta:
            p = ease_out(segment(t, S_DATA[0] + 0.12, S_DATA[0] + 0.20))
            text_alpha(layer,
                       (self.width - self.margin,
                        y + row_h * (len(rows) - 1) / 2 + fnt.size * 0.5),
                       meta, _font(max(14, round(self.unit * 0.026))), MUTED,
                       anchor="ra", alpha=p)
        return y + row_h * len(rows)

    def boundary_graphic(self, layer, draw, t, center, radius):
        p = phase(t, S_GRAPHIC)
        if p <= 0:
            return
        ring = [(center[0] + radius * math.cos(i / 72 * math.tau),
                 center[1] + radius * 0.62 * math.sin(i / 72 * math.tau)) for i in range(73)]
        draw_polyline_progress(draw, ring, p, tuple(HAIRLINE) + (235,), self.hair)
        people = ease_out(segment(t, S_GRAPHIC[0] + 0.06, S_GRAPHIC[1]))
        if people <= 0:
            return
        f = _font(max(20, round(self.unit * 0.055)))
        for index in range(3):
            x = center[0] - radius * 0.42 + index * radius * 0.42
            text_alpha(layer, (x, center[1] - f.size * 0.9), "▲", f, HAIRLINE, alpha=people)
            text_alpha(layer, (x + f.size * 0.18, center[1] - f.size * 0.30), "●", f, HAIRLINE,
                       alpha=people)
        box = round(self.unit * 0.055)
        draw.rectangle([center[0] + radius * 0.32, center[1] - box * 0.8,
                        center[0] + radius * 0.32 + box, center[1] + box * 0.2],
                       outline=tuple(HAIRLINE) + (int(235 * people),), width=2)
        arrow = ease_out(segment(t, S_GRAPHIC[0] + 0.10, S_GRAPHIC[1]))
        ax = center[0] - radius * 2.35
        tip = ax + radius * 1.05 * arrow
        draw.line([(ax, center[1]), (tip, center[1])], fill=tuple(HAIRLINE) + (235,), width=3)
        draw.line([(tip - 18, center[1] - 12), (tip, center[1]), (tip - 18, center[1] + 12)],
                  fill=tuple(HAIRLINE) + (235,), width=3)

    def compare_panels(self, layer, draw, t, top, bottom):
        cols = [c for c in (self.props.get("columns") or []) if c][:2]
        if len(cols) < 2:
            return
        gap = round(self.unit * 0.055)
        if str(self.props.get("axis") or "columns").lower() == "stacked":
            half = (bottom - top - gap) / 2
            rects = [(self.margin, top, self.width - self.margin, top + half),
                     (self.margin, top + half + gap, self.width - self.margin, bottom)]
        else:
            box_w = (self.inner - gap) / 2
            rects = [(self.margin, top, self.margin + box_w, bottom),
                     (self.margin + box_w + gap, top, self.width - self.margin, bottom)]
        accent = int(self.props.get("accent_side") or 0)
        f_head = _font(max(16, round(self.unit * 0.032)), bold=True)
        f_body = _font(max(15, round(self.unit * 0.028)))
        p = phase(t, S_GRAPHIC)
        for index, (col, rect) in enumerate(zip(cols, rects)):
            if p <= 0:
                continue
            draw.rectangle(rect, outline=tuple(HAIRLINE) + (int(225 * p),), width=max(1, self.hair))
            text_alpha(layer, (rect[0] + round(f_head.size * 0.55), rect[1] + round(f_head.size * 0.75)),
                       col.get("heading"), f_head, INK, alpha=p)
            if col.get("body"):
                draw_wrapped(
                    layer, draw,
                    (rect[0] + round(f_body.size * 0.55), rect[1] + round(f_head.size * 2.4)),
                    col["body"], f_body, MUTED,
                    (rect[2] - rect[0]) - round(f_body.size * 1.1),
                    max_lines=3,
                    alpha=ease_out(segment(t, S_GRAPHIC[0] + 0.05, S_GRAPHIC[1])),
                )
            if index == accent:
                box_p = ease_out(segment(t, S_ACCENT[0], S_ACCENT[1]))
                if box_p > 0:
                    ix = (rect[2] - rect[0]) / 2 * (1 - box_p)
                    iy = (rect[3] - rect[1]) / 2 * (1 - box_p)
                    draw.rectangle([rect[0] + ix, rect[1] + iy, rect[2] - ix, rect[3] - iy],
                                   outline=tuple(RED) + (int(230 * box_p),),
                                   width=max(2, round(self.unit * 0.0026)))
                for k, line in enumerate((col.get("callouts") or [])[:2]):
                    lp = ease_out(segment(t, S_ACCENT[0] + 0.03 + k * 0.02, S_ACCENT[1]))
                    if lp <= 0:
                        continue
                    ly = rect[1] + round(f_body.size * 3.5) + k * round(f_body.size * 2.1)
                    draw_wrapped(
                        layer, draw,
                        (rect[0] + round(f_body.size * 0.55), ly),
                        line, f_body, INK,
                        (rect[2] - rect[0]) - round(f_body.size * 1.1),
                        max_lines=2, alpha=lp,
                    )
                    lead = round(self.unit * 0.020)
                    draw.line([(rect[0], ly + round(f_body.size * 0.6)),
                               (rect[0] + lead, ly + round(f_body.size * 0.6))],
                              fill=tuple(RED) + (int(210 * lp),), width=max(1, self.hair))

    def range_bar(self, layer, draw, t, y):
        spec = self.props.get("range") or {}
        if not spec:
            return
        left, right = self.margin, self.width - self.margin
        draw_polyline_progress(draw, [(left, y), (right, y)], phase(t, S_GRAPHIC),
                               tuple(HAIRLINE) + (235,), self.hair)
        ticks = [str(v) for v in (spec.get("ticks") or [])][:4]
        f_tick = _font(max(13, round(self.unit * 0.024)))
        for index, tick in enumerate(ticks):
            tp = ease_out(segment(t, S_GRAPHIC[0] + 0.03 + index * 0.02, S_GRAPHIC[1]))
            if tp <= 0:
                continue
            tx = left + (right - left) * (index / max(1, len(ticks) - 1))
            draw.line([(tx, y), (tx, y + round(self.unit * 0.016))],
                      fill=tuple(HAIRLINE) + (int(220 * tp),), width=2)
            text_alpha(layer, (tx, y + round(self.unit * 0.028)), tick, f_tick, MUTED,
                       anchor="ma", alpha=tp)
        scan = ease_out(segment(t, S_DATA[0], S_DATA[0] + 0.10))
        if scan <= 0:
            return
        x0 = left + (right - left) * float(spec.get("start", 0.3))
        x1 = left + (right - left) * float(spec.get("end", 0.6))
        draw.line([(x0, y), (x0 + (x1 - x0) * scan, y)], fill=tuple(RED) + (235,),
                  width=max(3, round(self.unit * 0.004)))
        if scan >= 1:
            h = round(self.unit * 0.020) * ease_out(segment(t, S_DATA[0] + 0.10, S_DATA[0] + 0.14))
            for x in (x0, x1):
                draw.line([(x, y - h), (x, y + h)], fill=tuple(RED) + (235,), width=3)
        arrow = ease_out(segment(t, S_DATA[0] + 0.12, S_DATA[0] + 0.18))
        if arrow > 0:
            ax = x0 + (x1 - x0) * float(spec.get("arrow", 0.5))
            ty = y - round(self.unit * 0.030) * arrow
            draw.line([(ax, y), (ax, ty)], fill=tuple(HAIRLINE) + (235,), width=3)
            draw.line([(ax - 9, ty + 12), (ax, ty), (ax + 9, ty + 12)],
                      fill=tuple(HAIRLINE) + (235,), width=3)

    def matrix(self, layer, draw, t, top, bottom):
        rows, cols = (list(self.props.get("grid") or [8, 10]) + [8, 10])[:2]
        rows, cols = max(1, int(rows)), max(1, int(cols))
        filled = set(int(v) for v in (self.props.get("filled") or []))
        cell = self.inner / cols
        side = max(4, round(cell * 0.52))
        revealed = phase(t, S_GRAPHIC) * rows * cols
        if revealed <= 0:
            return
        fill_p = phase(t, S_DATA)
        row_h = (bottom - top) / rows
        for index in range(min(int(revealed), rows * cols)):
            r, c = divmod(index, cols)
            x = self.margin + c * cell + (cell - side) / 2
            y = top + r * row_h + (row_h - side) / 2
            box = [x, y, x + side, y + side]
            if index in filled and fill_p > 0:
                draw.rectangle(box, fill=tuple(HAIRLINE) + (int(235 * fill_p),))
            else:
                draw.rectangle(box, outline=tuple(HAIRLINE) + (225,), width=2)

    def process_boxes(self, layer, draw, t, y):
        nodes = [b for b in (self.props.get("boxes") or []) if b][:3]
        if not nodes:
            return y
        fnt = _font(max(16, round(self.unit * 0.030)))
        gap = round(self.unit * 0.10)
        box_w = (self.inner - gap * (len(nodes) - 1)) / len(nodes)
        box_h = round(fnt.size * 3.1)
        rects = []
        for index, node in enumerate(nodes):
            x = self.margin + index * (box_w + gap)
            rect = (x, y, x + box_w, y + box_h)
            rects.append(rect)
            p = ease_out(segment(t, S_GRAPHIC[0] + index * 0.04, S_GRAPHIC[0] + 0.06 + index * 0.04))
            if p <= 0:
                continue
            draw.rectangle(rect, outline=tuple(HAIRLINE) + (int(230 * p),), width=max(1, self.hair))
            text_alpha(layer, (x + round(fnt.size * 0.6), y + round(fnt.size * 0.72)),
                       node.get("text"), fnt, INK, alpha=p)
        arrow = ease_out(segment(t, S_GRAPHIC[0] + 0.10, S_GRAPHIC[1]))
        if arrow > 0 and len(rects) >= 2:
            y0 = y + box_h / 2
            x0, x1 = rects[0][2], rects[1][0]
            tip = x0 + (x1 - x0) * arrow
            w = max(2, round(self.unit * 0.0026))
            draw.line([(x0, y0), (tip, y0)], fill=tuple(RED) + (235,), width=w)
            draw.line([(tip - 14, y0 - 9), (tip, y0), (tip - 14, y0 + 9)],
                      fill=tuple(RED) + (235,), width=w)
            if self.props.get("arrow_label"):
                lp = ease_out(segment(t, S_GRAPHIC[1], min(1.0, S_GRAPHIC[1] + 0.04)))
                text_alpha(layer, ((x0 + x1) / 2, y0 - round(fnt.size * 1.3)),
                           self.props["arrow_label"], _font(max(13, round(self.unit * 0.024))),
                           MUTED, anchor="ma", alpha=lp)
        return y + box_h

    def influence_lines(self, layer, draw, t, y):
        items = [i for i in (self.props.get("influence") or []) if i][:2]
        if not items:
            return
        fnt = _font(max(15, round(self.unit * 0.028)))
        row = round(fnt.size * 2.6)
        for index, item in enumerate(items):
            p = ease_out(segment(t, S_CLOSE[0] + index * 0.03, S_CLOSE[1]))
            if p <= 0:
                continue
            top = y + index * row
            x_end = self.margin + (self.width - self.margin * 2) * p
            draw.line([(self.margin, top), (x_end, top)], fill=tuple(HAIRLINE) + (235,), width=2)
            up = str(item.get("direction") or "up").lower() != "down"
            dy = -9 if up else 9
            draw.line([(x_end - 14, top - dy), (x_end, top), (x_end - 14, top + dy)],
                      fill=tuple(HAIRLINE) + (235,), width=2)
            text_alpha(layer,
                       (self.margin, top + (round(fnt.size * 1.0) if up else round(-fnt.size * 1.9))),
                       item.get("text"), fnt, MUTED, alpha=p)


def _layout_title(board, layer, draw, t):
    board.eyebrow(layer, draw, t)
    board.rule(layer, draw, round(board.height * 0.083), t)
    y = board.headline(layer, draw, round(board.height * 0.185), t)
    board.subtitle(layer, t, y + round(board.unit * 0.02))
    board.rule(layer, draw, round(board.height * 0.50), t, window=S_GRAPHIC)
    board.numbers(layer, draw, t, round(board.height * 0.60))
    board.tags(layer, draw, t)
    board.footnote(layer, draw, t)


def _layout_number(board, layer, draw, t):
    board.eyebrow(layer, draw, t)
    board.rule(layer, draw, round(board.height * 0.083), t)
    y = board.headline(layer, draw, round(board.height * 0.150), t)
    board.subtitle(layer, t, y + round(board.unit * 0.02))
    scale = board.inner / 984
    base_y = round(board.height * 0.315)
    for index, cy in enumerate((0, 110, 220)):
        local = segment(phase(t, S_GRAPHIC), index * 0.18, 0.62 + index * 0.18)
        if local <= 0:
            continue
        px = board.margin + board.inner * (0.42 + index * 0.19)
        py = base_y + cy * (board.unit / 1152)
        for edge in iso_box(px, py, 96 * scale, 176 * scale):
            draw_polyline_progress(draw, edge, local, tuple(HAIRLINE) + (235,), 2)
        for edge in iso_monitor(px, py - 98 * scale, 46 * scale, 26 * scale):
            draw_polyline_progress(draw, edge, local, tuple(HAIRLINE) + (235,), 2)
    board.rule(layer, draw, round(board.height * 0.705), t, window=S_DATA)
    board.numbers(layer, draw, t, round(board.height * 0.750))
    board.tags(layer, draw, t)
    board.footnote(layer, draw, t)


def _layout_list(board, layer, draw, t):
    board.eyebrow(layer, draw, t)
    board.rule(layer, draw, round(board.height * 0.083), t)
    board.headline(layer, draw, round(board.height * 0.150), t)
    boundary = str(board.props.get("center_graphic") or "").lower() == "boundary"
    if boundary:
        board.boundary_graphic(layer, draw, t,
                               (board.width * 0.50, round(board.height * 0.335)),
                               board.unit * 0.185)
    board.list_rows(layer, draw, t,
                    round(board.height * (0.565 if boundary else 0.42)),
                    board.props.get("items"), meta=board.props.get("meta"),
                    bullet=bool(board.props.get("bullet")))
    board.footnote(layer, draw, t)
    board.tags(layer, draw, t)


def _layout_compare(board, layer, draw, t):
    board.eyebrow(layer, draw, t)
    board.rule(layer, draw, round(board.height * 0.083), t)
    board.headline(layer, draw, round(board.height * 0.150), t)
    board.compare_panels(layer, draw, t, round(board.height * 0.40), round(board.height * 0.72))
    board.footnote(layer, draw, t)
    board.tags(layer, draw, t)


def _layout_timeline(board, layer, draw, t):
    board.eyebrow(layer, draw, t)
    board.rule(layer, draw, round(board.height * 0.083), t)
    board.headline(layer, draw, round(board.height * 0.150), t)
    board.range_bar(layer, draw, t, round(board.height * 0.47))
    board.numbers(layer, draw, t, round(board.height * 0.58))
    board.footnote(layer, draw, t)
    board.tags(layer, draw, t)


def _layout_process(board, layer, draw, t):
    board.eyebrow(layer, draw, t)
    board.rule(layer, draw, round(board.height * 0.083), t)
    head_bottom = board.headline(layer, draw, round(board.height * 0.150), t)
    board.subtitle(layer, t, head_bottom + round(board.unit * 0.03))
    bottom = board.process_boxes(layer, draw, t, round(board.height * 0.42))
    board.influence_lines(layer, draw, t,
                          max(bottom + round(board.unit * 0.06), round(board.height * 0.68)))
    board.tags(layer, draw, t)
    board.footnote(layer, draw, t)


def _layout_gallery(board, layer, draw, t):
    board.eyebrow(layer, draw, t)
    board.rule(layer, draw, round(board.height * 0.083), t)
    board.headline(layer, draw, round(board.height * 0.150), t)
    board.matrix(layer, draw, t, round(board.height * 0.33), round(board.height * 0.60))
    rows = [str(v) for v in (board.props.get("items") or [])][:4]
    if rows:
        text_alpha(layer, (board.margin, round(board.height * 0.635)), " · ".join(rows),
                   _font(max(14, round(board.unit * 0.028))), MUTED, alpha=phase(t, S_DATA))
    board.rule(layer, draw, round(board.height * 0.705), t, window=S_DATA)
    board.numbers(layer, draw, t, round(board.height * 0.750))
    board.tags(layer, draw, t)
    board.footnote(layer, draw, t)


LAYOUTS = {
    "M_TITLE": _layout_title,
    "M_NUMBER": _layout_number,
    "M_LIST": _layout_list,
    "M_COMPARE": _layout_compare,
    "M_TIMELINE": _layout_timeline,
    "M_PROCESS": _layout_process,
    "M_GALLERY": _layout_gallery,
    "M_RANKING": _layout_list,
}


def render_frame(board, paper, t):
    """Draw one board frame at normalized time ``t`` (0.0-1.0)."""
    frame = paper.copy().convert("RGBA")
    layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    layout = LAYOUTS.get(str(board.props.get("template") or "M_TITLE").upper(), _layout_title)
    layout(board, layer, draw, board.build_progress(t))
    frame.alpha_composite(layer)
    return frame.convert("RGB")


def render_intel_board_clip(shot, output_size, output_path):
    """Render an animated intel-board clip plus its stable preview frame."""
    import core as c

    width, height = int(output_size[0]), int(output_size[1])
    plan = shot.get("motion_plan") or {}
    props = dict(plan.get("props") or {})
    props.update(shot.get("motion_data") or {})
    props.setdefault("title", shot.get("title") or shot.get("visual_subject") or "")
    props.setdefault("items", shot.get("keywords") or [])
    props["template"] = str(shot.get("motion_type") or "M_TITLE").upper()

    try:
        start, end = float(shot["start"]), float(shot["end"])
    except (KeyError, TypeError, ValueError):
        start, end = 0.0, 6.0
    duration = max(1.2, end - start)
    frames = min(MAX_FRAMES, max(2, round(duration * FPS)))
    # A segment split into several shots keeps one board clock, so the build
    # window is sized from the whole board rather than from a single part. The
    # floor still has to fit inside a short part, or its data layer never
    # appears before the shot ends.
    try:
        board_seconds = max(duration, float(props.get("duration") or 0))
    except (TypeError, ValueError):
        board_seconds = duration
    # Long boards spread the build instead of freezing early, but always keep
    # a settled tail so the final state reads as a result, not a stop.
    props.setdefault("build_seconds", round(min(
        MAX_BUILD_SECONDS,
        max(board_seconds * 0.62, min(MIN_BUILD_SECONDS, board_seconds * 0.9)),
    ), 3))

    board = Board(width, height, props)
    board.duration = duration
    board.offset = min(board.offset, max(0.0, board_seconds - duration))
    paper = make_paper(width, height)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    still = output_path.with_suffix(".png")
    render_frame(board, paper, 1.0).save(still, quality=95)

    temporary = output_path.with_suffix(".part.mp4")
    process = subprocess.Popen(
        [
            c.FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
            "-r", str(FPS), "-i", "-",
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-threads", "4", "-movflags", "+faststart",
            str(temporary),
        ],
        stdin=subprocess.PIPE,
    )
    assert process.stdin is not None
    try:
        for index in range(frames):
            process.stdin.write(render_frame(board, paper, index / max(1, frames - 1)).tobytes())
    finally:
        process.stdin.close()
    if process.wait() != 0:
        raise RuntimeError("intel_board 渲染失败")
    temporary.replace(output_path)
    return output_path, still
