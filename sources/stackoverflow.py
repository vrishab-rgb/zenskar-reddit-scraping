"""Stack Overflow / Stack Exchange discovery.

Engineers asking implementation questions about billing tools are
buyer-adjacent: they're either evaluating a tool, hitting a wall with
their current one, or implementing custom billing because their tool
can't handle the requirement. All three are signal for our marketing
team.

Stack Exchange API is free, no key required for low volume (300/day).
Documented at https://api.stackexchange.com/docs.
"""
import time
from datetime import datetime, timezone

import requests

from models import RedditHit

_API = "https://api.stackexchange.com/2.3/search/advanced"
# Tags most likely to surface billing/RevRec questions. Stack Exchange
# does AND on `tagged=`, OR via semicolons; we run one call per tag.
_TARGET_TAGS = [
    "stripe-billing", "chargebee", "zuora", "recurly",
    "billing", "subscription", "subscriptions",
    "revenue-recognition",
]
_INTER_CALL = 0.5


def _question_to_hit(q: dict, tag: str) -> RedditHit | None:
    qid = q.get("question_id")
    if not qid:
        return None
    title = (q.get("title") or "").strip()
    if not title:
        return None
    created_at = q.get("creation_date")
    ts = (
        datetime.fromtimestamp(int(created_at), tz=timezone.utc)
        if created_at else datetime.now(timezone.utc)
    )
    owner = (q.get("owner") or {}).get("display_name")
    return RedditHit(
        post_id=f"so:{qid}",
        # Reuse the subreddit field as the SO tag — keeps the schema flat.
        subreddit=f"so:{tag}",
        author=owner,
        title=title,
        body=None,  # Stack Exchange API gives only excerpts unless you ask for body
        permalink=q.get("link") or f"https://stackoverflow.com/q/{qid}",
        created_utc=ts,
        score=q.get("score"),
        num_comments=q.get("answer_count"),
        source="stackoverflow",
        matched_keywords=[tag],
    )


def fetch_tag(tag: str, page_size: int = 20) -> list[RedditHit]:
    """Pull recent questions tagged `tag`. We sort by creation desc to bias
    toward fresh content; older threads are stable lower-signal."""
    try:
        resp = requests.get(
            _API,
            params={
                "order": "desc",
                "sort": "creation",
                "tagged": tag,
                "site": "stackoverflow",
                "pagesize": page_size,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[so] tag {tag!r} failed: {e}")
        return []
    out: list[RedditHit] = []
    for q in data.get("items", []) or []:
        hit = _question_to_hit(q, tag)
        if hit is not None:
            out.append(hit)
    return out


def fetch_all(max_queries: int) -> list[RedditHit]:
    merged: dict[str, RedditHit] = {}
    used = 0
    for tag in _TARGET_TAGS:
        if used >= max_queries:
            break
        for hit in fetch_tag(tag):
            existing = merged.get(hit.post_id)
            if existing is None:
                merged[hit.post_id] = hit
            else:
                for k in hit.matched_keywords:
                    if k not in existing.matched_keywords:
                        existing.matched_keywords.append(k)
        used += 1
        if used < max_queries:
            time.sleep(_INTER_CALL)
    return list(merged.values())
