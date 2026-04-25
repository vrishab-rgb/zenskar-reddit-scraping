"""Hacker News discovery via Algolia's HN search API.

Why HN: same buyer audience as our Reddit ICP subs (technical CFOs,
founders evaluating billing infra, RevOps engineers). Algolia indexes
both stories AND comments, so we catch in-thread mentions for free.
No auth required, generous rate limits, returns JSON.

Critical config: we use `/search_by_date` (NOT `/search`) so results
come back newest-first, AND apply a 72-hour numeric filter — otherwise
the relevance sort dredges up high-karma 2018 stories about Chargebee
that aren't actionable. Marketing wants signals from the last few days,
not lifetime mentions.

Each match is normalized to a `RedditHit` (with subreddit='Hacker News'
and source='hacker_news') so the rest of the pipeline doesn't need to
know about platform differences.
"""
import time
from datetime import datetime, timedelta, timezone

import requests

from models import RedditHit

# search_by_date sorts newest-first; relevance sort (the default /search
# endpoint) buries fresh signal under high-karma archived stories.
_API = "https://hn.algolia.com/api/v1/search_by_date"
_ITEM_URL = "https://news.ycombinator.com/item?id={id}"
_INTER_CALL_SLEEP = 0.5  # Algolia is generous; keep it polite anyway.

# Only surface posts/comments from the last N hours. Tunable — for a
# weekly "best of" mode we'd raise this; for live alerts, fresh is the
# whole point.
_FRESHNESS_HOURS = 72


def _entry_to_hit(item: dict, query: str) -> RedditHit | None:
    """Algolia returns mixed 'story' + 'comment' results. We map both into
    RedditHit shape — the title field becomes the comment-or-story text and
    the body field carries the story body if present."""
    item_id = item.get("objectID")
    if not item_id:
        return None
    tags = item.get("_tags") or []
    is_comment = "comment" in tags

    if is_comment:
        # Comment matches: there's no title; use comment text as title-ish summary.
        title = (item.get("comment_text") or "").strip()
        body = None
        author = item.get("author")
    else:
        title = (item.get("title") or "").strip()
        body = (item.get("story_text") or "").strip() or None
        author = item.get("author")

    if not title and not body:
        return None

    created_at = item.get("created_at_i")
    if created_at:
        ts = datetime.fromtimestamp(int(created_at), tz=timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    return RedditHit(
        post_id=f"hn:{item_id}",
        subreddit="Hacker News",
        author=author,
        title=title[:500] or "(no title)",
        body=body,
        permalink=_ITEM_URL.format(id=item_id),
        created_utc=ts,
        score=item.get("points"),
        num_comments=item.get("num_comments"),
        source="hacker_news",
        matched_keywords=[query],
    )


def fetch_query(query: str, hits_per_page: int = 15) -> list[RedditHit]:
    """One Algolia search. Searches both story AND comment text on HN.
    Returns up to `hits_per_page` results sorted newest-first AND filtered
    to the last `_FRESHNESS_HOURS` hours — so we only surface signals
    that are actually still actionable."""
    cutoff = int((datetime.now(timezone.utc) - timedelta(hours=_FRESHNESS_HOURS)).timestamp())
    try:
        resp = requests.get(
            _API,
            params={
                "query": query,
                "hitsPerPage": hits_per_page,
                "tags": "(story,comment)",
                "numericFilters": f"created_at_i>{cutoff}",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[hn] query {query!r} failed: {e}")
        return []
    out: list[RedditHit] = []
    for item in data.get("hits", []) or []:
        hit = _entry_to_hit(item, query)
        if hit is not None:
            out.append(hit)
    return out


def fetch_all(queries: list[str], max_queries: int) -> list[RedditHit]:
    """Run up to `max_queries` queries, dedup by post_id, union matched_keywords.
    Yields a list of RedditHit ready to feed into the existing classification
    pipeline."""
    merged: dict[str, RedditHit] = {}
    used = 0
    for q in queries:
        if used >= max_queries:
            break
        for hit in fetch_query(q):
            existing = merged.get(hit.post_id)
            if existing is None:
                merged[hit.post_id] = hit
            else:
                for k in hit.matched_keywords:
                    if k not in existing.matched_keywords:
                        existing.matched_keywords.append(k)
        used += 1
        if used < max_queries:
            time.sleep(_INTER_CALL_SLEEP)
    return list(merged.values())
