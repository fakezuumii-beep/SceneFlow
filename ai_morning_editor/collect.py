"""Collect recent AI business candidates from first-party feeds and trusted media."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests


USER_AGENT = "SceneFlow-AI-Morning-Editor/0.1 (+local editorial tool)"

# This is intentionally a small, inspectable source list rather than a crawler.
FEEDS = (
    {"name": "OpenAI", "url": "https://openai.com/news/rss.xml", "tier": "official"},
    {"name": "Google AI", "url": "https://blog.google/technology/ai/rss/", "tier": "official"},
    {"name": "AWS Machine Learning Blog", "url": "https://aws.amazon.com/blogs/machine-learning/feed/", "tier": "official"},
    {"name": "NVIDIA AI Blog", "url": "https://blogs.nvidia.com/blog/category/deep-learning/feed/", "tier": "official"},
    {"name": "Hugging Face", "url": "https://huggingface.co/blog/feed.xml", "tier": "official"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "tier": "media"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "tier": "media"},
)

GITHUB_REPOSITORIES = (
    "openai/openai-python",
    "anthropics/anthropic-sdk-python",
    "googleapis/python-genai",
    "ollama/ollama",
    "huggingface/transformers",
    "vllm-project/vllm",
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def clean_html(value: str | None, limit: int = 1600) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", value or "", flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _text(node: ElementTree.Element, names: Iterable[str]) -> str:
    for name in names:
        found = node.find(name)
        if found is not None and (found.text or "").strip():
            return (found.text or "").strip()
    return ""


def _entry_link(node: ElementTree.Element, base_url: str) -> str:
    direct = _text(node, ("link",))
    if direct:
        return urljoin(base_url, direct)
    atom = "{http://www.w3.org/2005/Atom}"
    links = node.findall(f"{atom}link")
    for link in links:
        if link.attrib.get("rel", "alternate") == "alternate" and link.attrib.get("href"):
            return urljoin(base_url, link.attrib["href"])
    return ""


def _feed_entries(content: bytes, source: dict, cutoff: datetime, now: datetime) -> list[dict]:
    root = ElementTree.fromstring(content)
    atom = "{http://www.w3.org/2005/Atom}"
    dc = "{http://purl.org/dc/elements/1.1/}"
    content_ns = "{http://purl.org/rss/1.0/modules/content/}"
    entries = root.findall(".//item") or root.findall(f".//{atom}entry")
    result = []
    for entry in entries:
        title = clean_html(_text(entry, ("title", f"{atom}title")), 300)
        link = _entry_link(entry, source["url"])
        published_raw = _text(entry, (
            "pubDate", f"{dc}date", f"{atom}published", f"{atom}updated",
        ))
        published = parse_datetime(published_raw)
        # A missing timestamp cannot prove that an item belongs to the 24-hour window.
        # A small future tolerance handles feeds that round publication to the next hour.
        if not title or not link or not published or published < cutoff or published > now + timedelta(hours=2):
            continue
        description = clean_html(_text(entry, (
            "description", f"{atom}summary", f"{atom}content", f"{content_ns}encoded",
        )))
        result.append({
            "title": title,
            "summary": description,
            "source_name": source["name"],
            "source_url": link,
            "published_at": published.isoformat(),
            "source_tier": source["tier"],
            "collector": "feed",
        })
    return result


def collect_feeds(cutoff: datetime, now: datetime, session: requests.Session) -> tuple[list[dict], list[str]]:
    candidates: list[dict] = []
    warnings: list[str] = []
    for source in FEEDS:
        try:
            response = session.get(source["url"], timeout=(8, 25))
            response.raise_for_status()
            candidates.extend(_feed_entries(response.content, source, cutoff, now))
        except (requests.RequestException, ElementTree.ParseError, ValueError) as exc:
            warnings.append(f"{source['name']} 暂时无法读取：{type(exc).__name__}")
    return candidates, warnings


def collect_github(cutoff: datetime, now: datetime, session: requests.Session) -> tuple[list[dict], list[str]]:
    candidates: list[dict] = []
    warnings: list[str] = []
    for repository in GITHUB_REPOSITORIES:
        url = f"https://api.github.com/repos/{repository}/releases?per_page=5"
        try:
            response = session.get(url, timeout=(8, 25), headers={"Accept": "application/vnd.github+json"})
            response.raise_for_status()
            releases = response.json()
            if not isinstance(releases, list):
                raise ValueError("unexpected GitHub response")
            for release in releases:
                published = parse_datetime(release.get("published_at"))
                if not published or published < cutoff or published > now + timedelta(hours=2):
                    continue
                name = clean_html(release.get("name") or release.get("tag_name"), 240)
                candidates.append({
                    "title": f"{repository} 发布 {name}",
                    "summary": clean_html(release.get("body"), 1600),
                    "source_name": f"GitHub · {repository}",
                    "source_url": release.get("html_url") or url,
                    "published_at": published.isoformat(),
                    "source_tier": "official",
                    "collector": "github_release",
                })
        except (requests.RequestException, ValueError) as exc:
            warnings.append(f"GitHub {repository} 暂时无法读取：{type(exc).__name__}")
    return candidates, warnings


def collect(hours: int = 24, now: datetime | None = None) -> dict:
    now = (now or utc_now()).astimezone(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.7"})
    feed_items, feed_warnings = collect_feeds(cutoff, now, session)
    github_items, github_warnings = collect_github(cutoff, now, session)
    return {
        "window_start": cutoff.isoformat(),
        "window_end": now.isoformat(),
        "candidates": feed_items + github_items,
        "warnings": feed_warnings + github_warnings,
    }
