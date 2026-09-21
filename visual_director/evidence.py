"""EvidenceResolver v1: web search, screenshot, presentation, and caching."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import shutil
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

import requests
from PIL import Image, ImageFilter, ImageOps


_RESAMPLE_BOX = getattr(getattr(Image, 'Resampling', Image), 'BOX')


OFFICIAL_DOMAINS = {
    'openai': ('openai.com',),
    'anthropic': ('anthropic.com',),
    'google': ('google.com', 'blog.google', 'deepmind.google'),
    'gemini': ('google.com', 'blog.google', 'deepmind.google'),
    'meta': ('meta.com', 'about.fb.com', 'ai.meta.com'),
    'nvidia': ('nvidia.com',),
    'microsoft': ('microsoft.com',),
    'apple': ('apple.com',),
    'github': ('github.com',),
    'seedance': ('seed.bytedance.com', 'bytedance.com'),
    'bytedance': ('bytedance.com',),
}
KNOWN_NEWS = (
    'reuters.com', 'apnews.com', 'bloomberg.com', 'theverge.com',
    'techcrunch.com', 'wired.com', 'cnbc.com', 'ft.com', 'wsj.com',
)
OFFICIAL_ENTRY_URLS = {
    'openai': ('https://openai.com/news/', 'https://github.com/openai/'),
    'anthropic': ('https://www.anthropic.com/news', 'https://github.com/anthropics'),
    'google': ('https://blog.google/technology/ai/',),
    'gemini': ('https://blog.google/technology/ai/',),
    'meta': ('https://ai.meta.com/blog/',),
    'nvidia': ('https://nvidianews.nvidia.com/',),
    'microsoft': ('https://news.microsoft.com/',),
    'apple': ('https://www.apple.com/newsroom/',),
    'github': ('https://github.com/',),
}
LOW_QUALITY = (
    'pinterest.', 'facebook.com', 'x.com/', 'twitter.com/', 'reddit.com/',
    'medium.com/', 'blogspot.', 'quora.com/',
)
# Bumped whenever the capture or presentation policy changes, so a stale
# screenshot is re-taken instead of being reused with its old framing.
CAPTURE_POLICY = 'full-page-clean-overlays-v3'
PRESENT_POLICY = 'article-opening-window-v3'
# A page cited by several shots is sliced into this many different framings.
# The framing drifts down and pushes in across the article opening: the
# headline stays in frame, the text is twice the size of a whole-page fit, and
# the paywall / teaser tail that ends every news page is never reached.
SLICE_ZOOM_START = 1.7
SLICE_ZOOM_END = 2.6
# Paywalls, consent walls and newsletter modals dim the whole page and cover
# the article with a "subscribe to continue" panel, which made the evidence
# shots look broken. Anything matching these names and covering a real part of
# the viewport, plus any full-bleed fixed overlay, is dropped before capture.
OVERLAY_SCRIPT = """
() => {
  const named = /(paywall|subscribe|subscription|consent|cookie|gdpr|modal|overlay|newsletter|signup|sign-up|dialog|popup)/i;
  const viewport = Math.max(1, window.innerWidth * window.innerHeight);
  const removed = [];
  for (const element of Array.from(document.querySelectorAll('body *'))) {
    let style;
    try { style = getComputedStyle(element); } catch (error) { continue; }
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const rect = element.getBoundingClientRect();
    const share = Math.max(0, rect.width) * Math.max(0, rect.height) / viewport;
    const flagged = named.test(String(element.className || '')) || named.test(String(element.id || ''));
    const floating = style.position === 'fixed' || style.position === 'sticky';
    if ((floating && share > 0.25) || (flagged && share > 0.08)) {
      element.remove();
      removed.push(share.toFixed(2));
    }
  }
  document.documentElement.style.overflow = 'auto';
  document.body.style.overflow = 'auto';
  return removed.length;
}
"""


def _page(url):
    parsed = urlsplit(str(url or ''))
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return ''
    if parsed.username or parsed.password:
        return ''
    host = (parsed.hostname or '').strip().lower()
    if host in ('localhost', 'localhost.localdomain') or host.endswith('.local'):
        return ''
    try:
        address = ipaddress.ip_address(host)
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            return ''
    except ValueError:
        pass
    return parsed._replace(fragment='').geturl()


def _host(url):
    try:
        return urlsplit(url).hostname.lower().removeprefix('www.')
    except (AttributeError, ValueError):
        return ''


class _DuckParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.current = None
        self.capture = ''

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        classes = str(values.get('class') or '').split()
        if tag == 'a' and 'result__a' in classes:
            self.current = {'url': values.get('href', ''), 'title': ''}
        elif self.current and tag in ('a', 'div') and (
                'result__snippet' in classes or 'result__title' in classes):
            self.capture = ''

    def handle_data(self, data):
        if self.current:
            self.capture += data

    def handle_endtag(self, tag):
        if self.current and tag in ('a', 'div'):
            text = re.sub(r'\s+', ' ', self.capture).strip()
            if not self.current.get('title') and text:
                self.current['title'] = text
            elif text:
                self.current['snippet'] = text
            self.capture = ''
        if self.current and tag == 'div' and self.current.get('snippet'):
            self.results.append(self.current)
            self.current = None

    def close(self):
        super().close()
        if self.current:
            self.results.append(self.current)


def _duck_url(value):
    if value.startswith('//'):
        value = 'https:' + value
    parsed = urlsplit(value)
    if 'duckduckgo.com' in parsed.hostname and parsed.path.startswith('/l/'):
        target = parse_qs(parsed.query).get('uddg', [''])[0]
        return _page(unquote(target))
    return _page(value)


def _search_duckduckgo(query, timeout=20):
    response = requests.get(
        'https://html.duckduckgo.com/html/',
        params={'q': query},
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                          'AppleWebKit/537.36 Chrome/126 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.8,zh-CN;q=0.6',
        },
        timeout=(8, timeout),
    )
    if response.status_code != 200:
        return []
    parser = _DuckParser()
    parser.feed(response.text)
    parser.close()
    output = []
    for item in parser.results:
        url = _duck_url(item.get('url', ''))
        if url:
            output.append({
                'url': url,
                'title': html.unescape(item.get('title') or '')[:240],
                'snippet': html.unescape(item.get('snippet') or '')[:500],
                'provider': 'duckduckgo',
            })
    return output[:12]


def _search_bing(query, timeout=20):
    response = requests.get(
        'https://www.bing.com/search',
        params={'q': query, 'setlang': 'en'},
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36'},
        timeout=(8, timeout),
    )
    if response.status_code != 200:
        return []
    output = []
    for match in re.finditer(r'<li class="b_algo".*?</li>', response.text, re.S | re.I):
        block = match.group(0)
        link = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S | re.I)
        if not link:
            continue
        url = _page(html.unescape(link.group(1)))
        if not url:
            continue
        title = re.sub('<[^>]+>', '', link.group(2))
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', block, re.S | re.I)
        snippet = re.sub('<[^>]+>', '', snippet_match.group(1)) if snippet_match else ''
        output.append({
            'url': url,
            'title': html.unescape(re.sub(r'\s+', ' ', title)).strip()[:240],
            'snippet': html.unescape(re.sub(r'\s+', ' ', snippet)).strip()[:500],
            'provider': 'bing',
        })
    return output[:12]


def _search_google(query, timeout=20):
    response = requests.get(
        'https://www.google.com/search',
        params={'q': query, 'hl': 'en', 'gbv': '1', 'num': '10'},
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36'},
        timeout=(8, timeout),
    )
    if response.status_code != 200:
        return []
    output = []
    urls = re.findall(r'<a[^>]+href="([^"]+)"', response.text, re.I)
    titles = re.findall(r'<h3[^>]*>(.*?)</h3>', response.text, re.S | re.I)
    for raw_url, raw_title in zip(urls, titles):
        raw_url = html.unescape(raw_url)
        parsed = urlsplit(raw_url)
        if parsed.path == '/url':
            raw_url = parse_qs(parsed.query).get('q', [''])[0]
        url = _page(raw_url)
        if not url:
            continue
        title = html.unescape(re.sub('<[^>]+>', '', raw_title))
        title = re.sub(r'\s+', ' ', title).strip()
        output.append({
            'url': url,
            'title': title[:240],
            'snippet': '',
            'provider': 'google',
        })
    return output[:12]


def _search_techcrunch(query, timeout=20):
    query = re.sub(r'^site:\S+\s*', '', str(query or ''), flags=re.I).strip()
    query = re.sub(r'\b(?:official|announcement|release)\b', '', query, flags=re.I)
    query = re.sub(r'\s+', ' ', query).strip()
    response = requests.get(
        'https://techcrunch.com/wp-json/wp/v2/search',
        params={'search':query, 'per_page':8},
        headers={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36'},
        timeout=(8, timeout),
    )
    if response.status_code != 200:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    output = []
    for item in payload if isinstance(payload,list) else []:
        url = _page(item.get('url'))
        title = html.unescape(re.sub('<[^>]+>', '', str(item.get('title') or ''))).strip()
        if url and title:
            output.append({
                'url':url,'title':title[:240],'snippet':'',
                'provider':'techcrunch','direct_news':True,
            })
    return output[:8]


def search_web(query):
    output=[];seen=set()
    for provider in (_search_duckduckgo, _search_google, _search_bing, _search_techcrunch):
        try:
            values = provider(query)
        except requests.RequestException:
            values = []
        for item in values:
            if item.get('url') and item['url'] not in seen:
                seen.add(item['url']);output.append(item)
    return output[:20]


def _entity_names(segment):
    names = []
    for entity in segment.get('entities') or []:
        if isinstance(entity, dict) and entity.get('name'):
            names.append(str(entity['name']).strip())
        elif isinstance(entity, str) and entity.strip():
            names.append(entity.strip())
    return names


def build_search_queries(segment):
    entities = _entity_names(segment)
    target = str(segment.get('evidence_target') or segment.get('visual_subject') or '').strip()
    supplied = str(segment.get('search_query') or '').strip()
    subject = entities[0] if entities else str(segment.get('visual_subject') or '').strip()
    event = target or str(segment.get('text') or '').strip()
    if subject:
        event = re.sub(re.escape(subject), '', event, flags=re.I).strip(' -,，。')
    queries = []

    def add(value):
        value = re.sub(r'\s+', ' ', str(value or '')).strip()
        if value and value not in queries:
            queries.append(value[:240])

    add(supplied)
    if subject and event:
        add(f'{subject} {event} official announcement')
        add(f'{subject} {event} release')
        add(f'{subject} {event}')
        add(f'site:techcrunch.com {subject} {event}')
    elif event:
        add(f'{event} official page')
    domains = []
    for name in entities:
        domains.extend(OFFICIAL_DOMAINS.get(name.lower(), ()))
    for domain in domains[:2]:
        add(f'site:{domain} {event or subject}')
    return queries[:6]


def score_candidate(candidate, segment, query):
    url = candidate.get('url') or ''
    host = _host(url)
    score = 0
    reasons = []
    haystack = f"{candidate.get('title','')} {candidate.get('snippet','')} {url}".lower()
    names = [name.lower() for name in _entity_names(segment)]
    official = []
    for name in names:
        official.extend(OFFICIAL_DOMAINS.get(name, ()))
    parsed = urlsplit(url)
    path = parsed.path.strip('/')
    if host == 'github.com':
        matched = any(name in path.lower() for name in names)
        if matched and len(path.split('/')) >= 2:
            score += 90
            reasons.append('official_github_repo')
        elif matched:
            score += 45
            reasons.append('official_github_org')
    if official and any(host == domain or host.endswith('.' + domain) for domain in official):
        event_terms = [
            term.lower() for term in re.findall(
                r'[A-Za-z0-9][A-Za-z0-9.+-]{2,}', str(segment.get('evidence_target') or '')
            )
            if term.lower() not in {'official', 'page', 'announcement'}
        ]
        if event_terms and any(term in path.lower() for term in event_terms):
            score += 100
            reasons.append('official_event_page')
        elif path:
            score += 75
            reasons.append('official_domain')
        else:
            score += 45
            reasons.append('official_home')
    if any(host == domain or host.endswith('.' + domain) for domain in KNOWN_NEWS):
        score += 50
        reasons.append('known_news')
    if candidate.get('direct_news'):
        score += 40
        reasons.append('known_news_direct_search')
        subject_terms = {name.lower() for name in names}
        strong_terms = {
            term.lower() for term in re.findall(
                r'[A-Za-z0-9][A-Za-z0-9.+-]{3,}|[\u3400-\u9fff]{2,}',
                str(segment.get('evidence_target') or ''),
            )
            if term.lower() not in subject_terms
            and term.lower() not in {'official','announcement','release','new','update'}
        }
        if strong_terms and not any(term in haystack for term in strong_terms):
            score -= 60
            reasons.append('title_mismatch')
    if any(marker in url.lower() for marker in LOW_QUALITY):
        score -= 60
        reasons.append('low_quality')
    terms = [term.lower() for term in re.findall(r'[A-Za-z0-9][A-Za-z0-9.+-]{1,}|[\u3400-\u9fff]{2,}', f'{query} {segment.get("evidence_target","")}')]
    matches = sum(1 for term in set(terms) if term in haystack)
    score += min(30, matches * 3)
    if candidate.get('title'):
        score += 2
    if candidate.get('snippet'):
        score += 2
    date_match = re.search(r'/(20\d{2})/(\d{1,2})/', parsed.path)
    if date_match:
        try:
            published = datetime(int(date_match.group(1)), int(date_match.group(2)), 1, tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - published).days
            if age_days <= 120:
                score += 20
                reasons.append('recent')
            elif age_days > 540:
                score -= 20
                reasons.append('old')
        except ValueError:
            pass
    return score, reasons


def rank_candidates(queries, segment):
    candidates = {}
    for query in queries:
        for item in search_web(query):
            url = item['url']
            if url in candidates:
                continue
            score, reasons = score_candidate(item, segment, query)
            candidates[url] = {**item, 'score': score, 'score_reasons': reasons, 'query': query}
    for name in _entity_names(segment):
        for url in OFFICIAL_ENTRY_URLS.get(name.lower(), ()):
            entry = {
                'url':url,'title':f'{name} official','snippet':'','provider':'official_entry',
                # A bare organisation landing page (an org on GitHub, a blog
                # index) is a fallback for when nothing topical was found. It
                # must not outrank a page that actually covers the event.
                'score':40,'score_reasons':['official_entry'],'query':'official entity entry',
            }
            if url in candidates:
                candidates[url]['score'] = max(candidates[url]['score'], entry['score'])
                if 'official_entry' not in candidates[url]['score_reasons']:
                    candidates[url]['score_reasons'].append('official_entry')
            else:
                candidates[url] = entry
    return sorted(candidates.values(), key=lambda item: (-item['score'], item['url']))[:8]


def _bigrams(value, size=2):
    text = re.sub(r'\s+', '', str(value or ''))
    return {text[index:index + size] for index in range(max(0, len(text) - size + 1))}


def briefing_source_url(project, shot):
    """Return the briefing article a shot was written from, when it is clear.

    The morning editor writes one script paragraph per verified story, so the
    paragraph a shot belongs to identifies the article it should show. A weak
    or ambiguous paragraph match returns nothing and the caller falls back to
    searching, which keeps a wrong article out of the episode.
    """
    if _page(shot.get('evidence_url')):
        return ''
    briefing = project.get('morning_briefing') or {}
    stories = briefing.get('stories') if isinstance(briefing, dict) else None
    raw_script = project.get('script')
    script = str(raw_script.get('text') if isinstance(raw_script, dict) else raw_script or '')
    text = str(shot.get('text') or '').strip()
    if not stories or not script or len(text) < 4:
        return ''
    offset = script.find(text[:40])
    if offset < 0:
        offset = script.find(text)
    if offset < 0:
        return ''
    start = script.rfind('\n', 0, offset) + 1
    stop = script.find('\n', offset)
    paragraph = script[start:stop if stop >= 0 else len(script)].strip()
    if not paragraph:
        return ''
    gram = _bigrams(paragraph)
    ranked = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        url = _page(story.get('source_url')) or _page((story.get('source') or {}).get('source_url'))
        if not url:
            continue
        story_gram = _bigrams(
            f"{story.get('title') or ''}{story.get('summary') or ''}{story.get('business_impact') or ''}")
        if not story_gram:
            continue
        ranked.append((len(gram & story_gram) / len(story_gram), url))
    if not ranked:
        return ''
    ranked.sort(key=lambda item: -item[0])
    best = ranked[0][0]
    if best < .15:
        return ''
    if len(ranked) > 1 and best < ranked[1][0] * 1.3:
        return ''
    return ranked[0][1]


def _promo_top(thumb):
    """First row of a large flat coloured panel (paywall CTA, promo banner).

    News sites cover the lower half of an article with a big flat-coloured
    subscribe panel. Most of such a row is one colour, unlike a photo or an
    illustration, and the colour is saturated, unlike plain text.
    """
    width, height = thumb.size
    pixels = list(thumb.getdata())
    run = 0
    minimum = max(4, height // 33)
    for y in range(height):
        row = pixels[y * width:(y + 1) * width]
        spread = sum(max(pixel) - min(pixel) for pixel in row) / width
        if spread <= 40:
            run = 0
            continue
        means = [sum(pixel[channel] for pixel in row) / width for channel in range(3)]
        near = sum(
            1 for pixel in row
            if all(abs(pixel[channel] - means[channel]) < 48 for channel in range(3))
        ) / width
        if near > 0.7:
            run += 1
            if run >= minimum:
                return max(0, y - run + 1)
        else:
            run = 0
    return None


def content_extent(source):
    """Normalised ``(top, bottom)`` rows of a page that carry real content.

    A full-page screenshot ends in blank space and often in a paywall panel, so
    a slice panned there used to land on an empty frame or on a "subscribe to
    continue reading" prompt.
    """
    thumb = source.convert('L')
    if thumb.width > 240:
        thumb = thumb.resize((240, max(1, round(thumb.height * 240 / thumb.width))))
    mask = thumb.point(lambda value: 255 if value < 200 else 0)
    profile = list(mask.resize((1, mask.height), _RESAMPLE_BOX).getdata())
    threshold = 8
    rows = [value >= threshold for value in profile]
    if not any(rows):
        return 0.0, 1.0
    top = rows.index(True)
    bottom = len(rows) - 1 - rows[::-1].index(True)
    bottom_ratio = (bottom + 1) / len(rows)
    try:
        colour = source.convert('RGB')
        if colour.width > 160:
            colour = colour.resize((160, max(1, round(colour.height * 160 / colour.width))))
        promo = _promo_top(colour)
    except Exception:
        promo = None
    if promo:
        promo_ratio = promo / colour.height
        if top / len(rows) < promo_ratio < bottom_ratio:
            bottom_ratio = promo_ratio
    return top / len(rows), bottom_ratio


def part_window(source_size, output_size, part, parts, zoom=None, content=None):
    """Frame one slice of a page that several shots cite.

    A reused page used to be presented as the same full screenshot for every
    shot, so a 45-shot evidence run showed four identical pictures cut against
    each other. Each slice now drifts down and pushes into the article opening,
    which keeps the headline in frame, makes the text readable, and stops short
    of the paywall / teaser tail that ends every news page.
    """
    width, height = (max(1.0, float(source_size[0])), max(1.0, float(source_size[1])))
    top_ratio, bottom_ratio = content or (0.0, 1.0)
    top_ratio = min(max(0.0, float(top_ratio)), 1.0)
    bottom_ratio = min(max(top_ratio + 0.05, float(bottom_ratio)), 1.0)
    content_top = top_ratio * height
    content_h = max(8.0, (bottom_ratio - top_ratio) * height)
    count = max(1, int(parts or 1))
    index = max(1, min(count, int(part or 1))) - 1
    progress = index / (count - 1) if count > 1 else 0.0
    aspect = (output_size[0] / output_size[1]) if output_size and output_size[1] else 1.0
    if zoom:
        scale = max(1.0, float(zoom))
    else:
        # The zoom has to fit inside the content rows, otherwise the slice would
        # spill into the paywall the extent already cut away.
        fits = width / max(1e-6, aspect * content_h) if aspect > 0 else 1.0
        start = min(max(SLICE_ZOOM_START, fits), SLICE_ZOOM_END)
        end = min(max(start * 1.35, SLICE_ZOOM_END), start * 1.6)
        scale = start + (end - start) * progress
    window_w = min(width, max(8.0, width / scale))
    window_h = window_w / aspect if aspect > 0 else content_h
    window_h = min(window_h, content_h)
    window_w = min(width, window_h * aspect)
    y = content_top + max(0.0, content_h - window_h) * progress
    y = min(max(0.0, y), max(0.0, height - window_h))
    return {
        'x': max(0.0, (width - window_w) / 2) / width,
        'y': y / height,
        'width': window_w / width,
        'height': window_h / height,
    }


class WebScreenshotService:
    def __init__(self, width=1440, height=1800):
        self.width = width
        self.height = height

    def _launch(self, playwright):
        errors = []
        for channel in ('msedge', 'chrome'):
            try:
                return playwright.chromium.launch(channel=channel, headless=True)
            except Exception as exc:
                errors.append(f'{channel}: {exc}')
        try:
            return playwright.chromium.launch(headless=True)
        except Exception as exc:
            errors.append(f'chromium: {exc}')
        raise RuntimeError('没有可用的无头浏览器；' + '；'.join(errors)[-1200:])

    def capture(self, url, target):
        from playwright.sync_api import sync_playwright
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.part.png')
        try:
            with sync_playwright() as playwright:
                browser = self._launch(playwright)
                try:
                    context = browser.new_context(
                        viewport={'width': self.width, 'height': self.height},
                        locale='en-US',
                        color_scheme='light',
                        ignore_https_errors=True,
                    )
                    page = context.new_page()
                    page.goto(url, wait_until='domcontentloaded', timeout=30000)
                    try:
                        page.wait_for_load_state('networkidle', timeout=8000)
                    except Exception:
                        pass
                    self._settle(page)
                    page.screenshot(path=str(temporary), full_page=True, animations='disabled')
                    title = page.title()
                    blocked = title.strip().lower()
                    if any(marker in blocked for marker in (
                            'just a moment', 'attention required', 'access denied',
                            'verify you are human', 'captcha', 'security check')):
                        raise RuntimeError(f'网页返回了验证/拦截页：{title.strip() or "unknown"}')
                    context.close()
                finally:
                    browser.close()
            if not temporary.is_file() or temporary.stat().st_size < 1024:
                raise RuntimeError('网页截图结果为空')
            temporary.replace(target)
            return {'path': target, 'title': title}
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _settle(page):
        """Let lazy hero images and embeds paint before the screenshot.

        News sites load the article image only once it scrolls into view, so a
        viewport-only capture of the top of the page rendered as a large black
        rectangle in the middle of the frame.
        """
        try:
            page.evaluate(
                "async () => {"
                "  const step = Math.max(200, window.innerHeight * 0.8);"
                "  for (let y = 0; y < document.body.scrollHeight; y += step) {"
                "    window.scrollTo(0, y);"
                "    await new Promise(r => setTimeout(r, 60));"
                "  }"
                "  window.scrollTo(0, 0);"
                "}"
            )
        except Exception:
            pass
        for script in (
            "Array.from(document.images).every(i => i.complete)",
            "Array.from(document.querySelectorAll('video')).every(v => v.readyState >= 2 || !v.currentSrc)",
        ):
            try:
                page.wait_for_function(script, timeout=6000)
            except Exception:
                pass
        try:
            page.evaluate(OVERLAY_SCRIPT)
        except Exception:
            pass
        try:
            page.wait_for_timeout(400)
        except Exception:
            pass


class EvidencePresenter:
    def __init__(self, output_size, fps=30):
        self.width, self.height = output_size
        self.fps = fps

    def image(self, source, target, focus=None, zoom=1.05, part=1, parts=1):
        source = Image.open(source).convert('RGB')
        if not focus and int(parts or 1) > 1:
            explicit = float(zoom or 0)
            focus = part_window(
                source.size, (self.width, self.height), part, parts,
                explicit if explicit > 1.05 else None, content_extent(source),
            )
        focus = focus or {}
        box = [
            float(focus.get('x', 0)), float(focus.get('y', 0)),
            float(focus.get('width', 1)), float(focus.get('height', 1)),
        ]
        width, height = source.size
        left = max(0, min(width - 2, round(box[0] * width)))
        top = max(0, min(height - 2, round(box[1] * height)))
        right = max(left + 2, min(width, round((box[0] + box[2]) * width)))
        bottom = max(top + 2, min(height, round((box[1] + box[3]) * height)))
        crop = source.crop((left, top, right, bottom))

        background = ImageOps.fit(source, (self.width, self.height), method=Image.Resampling.LANCZOS)
        background = background.filter(ImageFilter.GaussianBlur(max(10, self.width // 45)))
        overlay = Image.new('RGB', background.size, '#102c2a')
        background = Image.blend(background, overlay, .42)

        margin = max(24, round(min(self.width, self.height) * .055))
        available = (self.width - margin * 2, self.height - margin * 2)
        foreground = ImageOps.contain(crop, available, method=Image.Resampling.LANCZOS)
        x = (self.width - foreground.width) // 2
        y = (self.height - foreground.height) // 2
        shadow = Image.new('RGBA', background.size, (0, 0, 0, 0))
        shadow_box = Image.new('RGBA', (foreground.width + 28, foreground.height + 28), (0, 0, 0, 0))
        shadow_box.paste((0, 0, 0, 110), (14, 14, 14 + foreground.width, 14 + foreground.height))
        shadow.alpha_composite(shadow_box.filter(ImageFilter.GaussianBlur(14)), (x - 14, y - 14))
        background = Image.alpha_composite(background.convert('RGBA'), shadow).convert('RGB')
        background.paste(foreground, (x, y))
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        background.save(target, quality=95)
        return target

    def clip(self, image, target, duration, fade=0.0):
        """Encode one still as a clip.

        ``fade`` defaults to 0 because a screenshot is a cut, not a generated
        still: fading in from black made every evidence cut flash black.
        """
        import core as c
        from .still_motion import stable_still_filter
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        frames = max(1, round(float(duration) * self.fps))
        temporary = target.with_suffix('.part.mp4')
        filters = stable_still_filter(self.width, self.height, self.fps, fade)
        c.run([c.FFMPEG, '-y', '-v', 'error', '-loop', '1', '-i', image,
               '-vf', filters, '-frames:v', str(frames), '-an', '-c:v', 'libx264',
               '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p',
               '-threads', '4', '-movflags', '+faststart', temporary], timeout=1200)
        temporary.replace(target)
        return target


class EvidenceResolver:
    def __init__(self, screenshot=None):
        self.screenshot = screenshot or WebScreenshotService()

    def _page_image(self, url, folder):
        """Capture a page once and reuse it for every shot that cites it.

        Episodes often show the same source page across many shots, and a full
        headless capture of a news site costs tens of seconds, so the raw page
        image is cached by URL and only the presenter runs per shot.
        """
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        width = int(getattr(self.screenshot, 'width', 1440) or 1440)
        height = int(getattr(self.screenshot, 'height', 1800) or 1800)
        key = hashlib.sha256(json.dumps({
            'url': url,
            'size': [width, height],
            'capture': CAPTURE_POLICY,
        }, sort_keys=True).encode()).hexdigest()[:24]
        image = folder / f'{key}.png'
        metadata = folder / f'{key}.json'
        if image.is_file() and metadata.is_file():
            return image, json.loads(metadata.read_text(encoding='utf-8'))
        capture = self.screenshot.capture(url, image)
        info = {'url': url, 'title': capture.get('title') or '', 'captured_at': time.time()}
        metadata.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
        return image, info

    def resolve(self, project, shot, output_size, options=None):
        import core as c
        role = str(shot.get('visual_role') or 'E').upper()
        if role == 'R':
            role = 'E'
        folder = c.project_dir(project['id'])
        cache = folder / 'cache' / 'evidence'
        cache.mkdir(parents=True, exist_ok=True)
        source_url = briefing_source_url(project, shot)
        cache_key = hashlib.sha256(json.dumps({
            'shot': shot.get('id'), 'target': shot.get('evidence_target'),
            'query': shot.get('search_query'), 'url': shot.get('evidence_url'),
            'briefing_source': source_url,
            'crop': shot.get('evidence_crop'), 'focus': shot.get('evidence_focus'),
            'part': shot.get('visual_part'), 'parts': shot.get('visual_parts'),
            'size': output_size, 'duration': round(float(shot['end']) - float(shot['start']), 3),
            'still_policy': 'static-hold-v2', 'present_policy': PRESENT_POLICY,
        }, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
        image = cache / f'{cache_key}.png'
        clip = cache / f'{cache_key}.mp4'
        metadata_path = cache / f'{cache_key}.json'

        if not clip.is_file():
            url = _page(shot.get('evidence_url')) or ''
            # A page the operator or the briefing already names is tried first.
            # Searching the web eagerly cost several search round trips per shot
            # even when that page resolved, which is what made a briefing
            # episode crawl through its evidence shots.
            known = []
            if url:
                known.append({
                    'url': url, 'title': '', 'score': 100,
                    'score_reasons': ['user_url'], 'query': '',
                })
            elif source_url:
                known.append({
                    'url': source_url, 'title': '', 'score': 100,
                    'score_reasons': ['briefing_source'], 'query': '',
                })
            capture = None
            last_error = None
            source_image = None
            candidate = None
            for item in known:
                try:
                    candidate = item
                    url = candidate['url']
                    source_image, capture = self._page_image(url, cache / 'pages')
                    shutil.copy2(source_image, image)
                    break
                except Exception as exc:
                    last_error = exc
                    image.unlink(missing_ok=True)
            if capture is None:
                # Only pay for a web search when the known page did not resolve.
                for item in rank_candidates(build_search_queries(shot), shot)[:4]:
                    try:
                        candidate = item
                        url = candidate['url']
                        source_image, capture = self._page_image(url, cache / 'pages')
                        shutil.copy2(source_image, image)
                        break
                    except Exception as exc:
                        last_error = exc
                        image.unlink(missing_ok=True)
            if capture is None:
                raise RuntimeError(f'证据页面截图失败：{last_error or "没有候选页面"}')
            presenter = EvidencePresenter(output_size)
            presented = presenter.image(
                image, cache / f'{cache_key}-presented.png',
                shot.get('evidence_focus') or shot.get('evidence_crop'),
                float(shot.get('evidence_zoom') or 1.05),
                shot.get('visual_part') or 1, shot.get('visual_parts') or 1,
            )
            duration = max(.1, float(shot['end']) - float(shot['start']))
            presenter.clip(presented, clip, duration)
            c.atomic_json(metadata_path, {
                'url': url, 'title': capture.get('title') or candidate.get('title') or '',
                'candidate': candidate, 'queries': build_search_queries(shot),
                'captured_at': time.time(),
            })

        asset_dir = folder / 'assets'
        final_clip = asset_dir / f'evidence-{cache_key}.mp4'
        final_image = asset_dir / f'evidence-{cache_key}.png'
        if not final_clip.exists():
            shutil.copy2(clip, final_clip)
        if not final_image.exists():
            presented=cache / f'{cache_key}-presented.png'
            shutil.copy2(presented if presented.is_file() else image, final_image)
        metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.is_file() else {}
        return {
            'asset_type': 'video',
            'asset_path': final_clip.relative_to(folder).as_posix(),
            'preview_path': final_image.relative_to(folder).as_posix(),
            'duration': round(max(.1, float(shot['end']) - float(shot['start'])), 3),
            'source': metadata.get('url') or shot.get('evidence_url') or '',
            'metadata': {
                'resolver': 'evidence',
                'evidence_url': metadata.get('url') or shot.get('evidence_url'),
                'page_title': metadata.get('title'),
                'search_candidate': metadata.get('candidate'),
                'crop': shot.get('evidence_crop'),
                'focus': shot.get('evidence_focus'),
                'zoom': shot.get('evidence_zoom', 1.05),
                'part': shot.get('visual_part') or 1,
                'parts': shot.get('visual_parts') or 1,
                'present_policy': PRESENT_POLICY,
                'role_executed_as': role,
            },
            'status': 'ready',
        }
