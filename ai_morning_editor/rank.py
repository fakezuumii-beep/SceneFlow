"""Business-value scoring and deterministic event de-duplication."""
from __future__ import annotations

import re
from difflib import SequenceMatcher


BUSINESS_TERMS = {
    "pricing": 4.0, "price": 3.5, "cost": 3.0, "revenue": 3.5, "enterprise": 3.0,
    "funding": 4.0, "valuation": 4.0, "acquisition": 4.5, "acquire": 4.0, "merger": 4.5,
    "launch": 2.8, "release": 2.2, "api": 3.0, "developer": 1.8, "business": 2.5,
    "customer": 2.0, "partnership": 3.0, "contract": 3.5, "cloud": 2.0, "agent": 1.6,
    "ipo": 4.5, "go public": 4.0, "valuation": 4.0, "data center": 3.5,
    "regulation": 3.0, "regulatory": 3.0, "security": 2.8, "supply chain": 3.5,
    "safety": 2.4, "evaluation": 2.0, "standard": 1.8, "slow down": 2.0,
    "上市": 4.0, "价格": 4.0, "降价": 4.5, "成本": 3.5, "收入": 3.5, "融资": 4.0,
    "估值": 4.0, "收购": 4.5, "并购": 4.5, "发布": 2.5, "企业": 3.0, "开发者": 2.0,
    "商业": 3.0, "合作": 3.0, "订单": 3.5, "采购": 3.5, "开放": 1.5,
    "上市": 4.5, "数据中心": 3.5, "监管": 3.0, "安全": 2.8, "供应链": 3.5,
    "评估": 2.0, "标准": 1.8, "放缓": 2.0,
}

LOW_VALUE_TERMS = {
    "paper": 2.5, "benchmark": 2.0, "leaderboard": 2.0, "research": 1.2,
    "论文": 2.5, "基准": 2.0, "排行榜": 2.0, "研究": 1.0,
}

STOPWORDS = {
    "the", "a", "an", "to", "of", "for", "and", "in", "on", "with", "from", "says",
    "its", "is", "are", "new", "ai", "artificial", "intelligence", "发布", "宣布", "推出",
}


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", title.lower().replace("’", "'"))
    return {word for word in words if word not in STOPWORDS and len(word) > 1}


def score_candidate(item: dict) -> float:
    text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    score = 4.0 if item.get("source_tier") == "official" else 2.0
    hits = 0
    for term, weight in BUSINESS_TERMS.items():
        if term in text:
            score += weight
            hits += 1
    for term, penalty in LOW_VALUE_TERMS.items():
        if term in text:
            score -= penalty
    if item.get("collector") == "github_release":
        score -= 1.5  # Routine patch releases should not crowd out commercial events.
    if len(item.get("summary", "")) >= 180:
        score += 0.8
    if hits == 0:
        score -= 2.0
    return round(max(score, 0.0), 2)


def same_event(left: dict, right: dict) -> bool:
    a = left.get("title", "").lower()
    b = right.get("title", "").lower()
    ratio = SequenceMatcher(None, a, b).ratio()
    ta, tb = _tokens(a), _tokens(b)
    overlap = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return ratio >= 0.58 or (len(ta & tb) >= 3 and overlap >= 0.6)


def rank_and_dedupe(candidates: list[dict], limit: int = 12) -> list[dict]:
    scored = []
    seen_urls = set()
    for raw in candidates:
        if raw.get("source_url") in seen_urls:
            continue
        seen_urls.add(raw.get("source_url"))
        item = dict(raw)
        item["rank_score"] = score_candidate(item)
        item["supporting_sources"] = []
        scored.append(item)
    scored.sort(key=lambda item: (item["rank_score"], item["published_at"]), reverse=True)

    groups: list[dict] = []
    for item in scored:
        match = next((existing for existing in groups if same_event(existing, item)), None)
        if match is None:
            groups.append(item)
            continue
        match["supporting_sources"].append({
            "source_name": item["source_name"],
            "source_url": item["source_url"],
            "published_at": item["published_at"],
        })
        # Prefer a first-party page as the primary source without losing the stronger score.
        if item.get("source_tier") == "official" and match.get("source_tier") != "official":
            support = {
                "source_name": match["source_name"], "source_url": match["source_url"],
                "published_at": match["published_at"],
            }
            item["supporting_sources"] = match["supporting_sources"] + [support]
            item["rank_score"] = max(item["rank_score"], match["rank_score"])
            groups[groups.index(match)] = item
    groups.sort(key=lambda item: (item["rank_score"], item["published_at"]), reverse=True)
    return groups[:limit]
