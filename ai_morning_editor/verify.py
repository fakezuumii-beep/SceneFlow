"""Verify source pages and extract a bounded evidence excerpt."""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

from .collect import USER_AGENT


PRIMARY_DOMAINS = {
    "openai.com": "OpenAI",
    "anthropic.com": "Anthropic",
    "ai.google": "Google AI",
    "blog.google": "Google",
    "deepmind.google": "Google DeepMind",
    "microsoft.com": "Microsoft",
    "github.com": "GitHub",
    "meta.com": "Meta",
    "ai.meta.com": "Meta AI",
    "nvidia.com": "NVIDIA",
    "aws.amazon.com": "AWS",
    "huggingface.co": "Hugging Face",
    "rubygems.org": "RubyGems",
    "whitehouse.gov": "The White House",
    "epa.gov": "U.S. EPA",
}


class ParagraphParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("p", "h1", "h2"):
            self._capture = True
        if tag == "a":
            self._href = dict(attrs).get("href", "")
            self._anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("p", "h1", "h2"):
            self._capture = False
            self._parts.append("\n")
        if tag == "a" and self._href:
            self.links.append((self._href, re.sub(r"\s+", " ", " ".join(self._anchor_parts)).strip()))
            self._href = ""
            self._anchor_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)
        if self._href:
            self._anchor_parts.append(data)

    def text(self) -> str:
        value = html.unescape(" ".join(self._parts))
        return re.sub(r"\s+", " ", value).strip()


def _primary_name(host: str) -> str | None:
    host = host.lower().split(":", 1)[0]
    for domain, name in PRIMARY_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


def _meaningful_tokens(value: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "this", "that", "about", "news", "blog", "more", "here", "open", "read", "ai"}
    return {token for token in re.findall(r"[a-z0-9]{3,}", value.lower()) if token not in stop}


def _primary_candidates(page_url: str, title: str, links: list[tuple[str, str]]) -> list[dict]:
    title_tokens = _meaningful_tokens(title)
    scored = []
    seen = set()
    for raw_url, anchor in links:
        url = urljoin(page_url, html.unescape(raw_url)).split("#", 1)[0]
        parts = urlsplit(url)
        name = _primary_name(parts.netloc)
        if not name or url in seen or parts.path in ("", "/"):
            continue
        seen.add(url)
        linked_tokens = _meaningful_tokens(anchor + " " + parts.path.replace("-", " "))
        overlap = len(title_tokens & linked_tokens)
        company_match = any(token in title.lower() for token in _meaningful_tokens(name))
        score = overlap + (3 if company_match else 0) + (1 if overlap >= 2 else 0)
        if score >= 2:
            scored.append({"source_name": name, "source_url": url, "trace_score": score})
    return sorted(scored, key=lambda item: item["trace_score"], reverse=True)


def _article_body_from_jsonld(page: str) -> str:
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            payload = json.loads(html.unescape(raw))
        except (ValueError, TypeError):
            continue
        queue = payload if isinstance(payload, list) else [payload]
        while queue:
            value = queue.pop(0)
            if isinstance(value, dict):
                body = value.get("articleBody")
                if isinstance(body, str) and len(body) > 120:
                    return re.sub(r"\s+", " ", body).strip()
                graph = value.get("@graph")
                if isinstance(graph, list):
                    queue.extend(graph)
    return ""


def verify_candidates(candidates: list[dict]) -> list[dict]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8,zh-CN;q=0.7"})
    verified = []
    for raw in candidates:
        item = dict(raw)
        page_text = ""
        page_links: list[tuple[str, str]] = []
        status = None
        final_url = item["source_url"]
        try:
            response = session.get(item["source_url"], timeout=(8, 25), allow_redirects=True)
            status = response.status_code
            response.raise_for_status()
            final_url = response.url
            if "html" in response.headers.get("content-type", "").lower():
                page_text = _article_body_from_jsonld(response.text)
                if not page_text:
                    parser = ParagraphParser()
                    parser.feed(response.text)
                    page_text = parser.text()
                    page_links = parser.links
                else:
                    parser = ParagraphParser()
                    parser.feed(response.text)
                    page_links = parser.links
        except (requests.RequestException, ValueError):
            pass
        evidence = page_text or item.get("summary", "")
        item["source_url"] = final_url
        item["evidence"] = evidence[:5000]
        item["verified"] = bool(status and 200 <= status < 400 and len(evidence) >= 120)
        base = 0.76 if item.get("source_tier") == "official" else 0.66
        if item["verified"]:
            base += 0.12
        if item.get("supporting_sources"):
            base += 0.06
        if len(evidence) < 120:
            base -= 0.12
        else:
            # Every verified media item used to land on exactly 0.78, so the
            # field could not tell a one-paragraph note from a full report.
            # Weight how much article body the run actually managed to read.
            base += 0.10 * min(1.0, len(evidence) / 3000)
        item["confidence"] = round(min(0.98, max(0.35, base)), 2)
        item["verification_http_status"] = status
        if item.get("source_tier") == "official":
            item["primary_source"] = {
                "source_name": item["source_name"], "source_url": item["source_url"],
                "published_at": item["published_at"], "verified": item["verified"],
            }
        else:
            item["media_source"] = {
                "source_name": item["source_name"], "source_url": item["source_url"],
                "published_at": item["published_at"], "verified": item["verified"],
            }
            for primary in _primary_candidates(final_url, item.get("title", ""), page_links)[:3]:
                try:
                    traced = session.get(primary["source_url"], timeout=(8, 20), allow_redirects=True)
                    traced.raise_for_status()
                    if len(traced.content) < 500:
                        continue
                    item["primary_source"] = {
                        "source_name": primary["source_name"], "source_url": traced.url,
                        "verified": True,
                    }
                    break
                except requests.RequestException:
                    continue
        verified.append(item)
    return verified
