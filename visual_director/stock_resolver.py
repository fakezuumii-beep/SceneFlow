"""Provider-neutral query planning for generic stock B-roll."""
from __future__ import annotations


def resolve_stock_queries(segment, limit=3):
    values = []
    for key in ("stock_search_query", "search_query", "visual_subject"):
        value = str(segment.get(key) or "").strip()
        if value and value not in values:
            values.append(value)
    for value in segment.get("stock_search_query_alt") or []:
        query = str(value or "").strip()
        if query and query not in values:
            values.append(query)
    return values[:limit]


def queries_for_shot(shot, limit=3):
    return resolve_stock_queries(shot, limit)
