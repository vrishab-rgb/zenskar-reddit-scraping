"""Stack Overflow / Stack Exchange discovery.

Lesson learned the hard way: pulling every recent question tagged
'chargebee' or 'stripe-billing' floods alerts with routine integration
questions ('how do I add a webhook?'). Engineers asking how to USE a
tool isn't a buying signal — only engineers EVALUATING / MIGRATING /
COMPARING tools is.

So we pre-filter at the source: only questions whose title contains
buyer-intent terminology pass through to stage-1. Drops volume by ~90%
but keeps the 10% that's actually marketing-relevant.

Stack Exchange API is free, no key required for low volume (300/day).
Documented at https://api.stackexchange.com/docs.
"""
import re
import time
from datetime import datetime, timezone

import requests

from models import RedditHit

_API = "https://api.stackexchange.com/2.3/search/advanced"
# Vendor-specific tags only — generic 'billing', 'subscription' tags are
# too noisy (mostly Stripe Charges API questions, not billing-platform
# evaluations). Each call is tagged="<tag>".
_TARGET_TAGS = [
    "stripe-billing", "chargebee", "zuora", "recurly",
    "revenue-recognition",
]

# Title must contain one of these to qualify as buyer-intent. We anchor
# at a leading word boundary so 'alternative' matches at word start but
# embedded substrings (e.g. inside a code identifier) don't, and use
# explicit suffix alternatives where needed instead of trailing \b — that
# would otherwise reject 'alternatives' (\b doesn't sit between 'v' and 'e').
_BUYER_INTENT_RE = re.compile(
    r"\b(?:"
    r"alternativ(?:e|es)|"
    r"vs|versus|"
    r"migrat(?:e|ing|ion|ions)|"
    r"switching|"
    r"moved (?:from|off)|"
    r"recommend(?:s|ed|ation|ations)?|"
    r"compar(?:e|ed|ing|ison|isons)|"
    r"evaluat(?:e|ing|ion|ions)|"
    r"better than|"
    r"best (?:billing|tool|platform|software)|"
    r"replac(?:e|ing|ement)"
    r")\b",
    re.IGNORECASE,
)

_INTER_CALL = 0.5


def _has_buyer_intent(title: str) -> bool:
    return bool(_BUYER_INTENT_RE.search(title or ""))


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
        if not _has_buyer_intent(q.get("title", "")):
            continue
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
