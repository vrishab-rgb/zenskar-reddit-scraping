"""Google search for site:reddit.com via serper.dev.

This is the single highest-leverage source we have. Reddit's own search
indexes only post titles. Google indexes the full post body AND comment
threads, and serper.dev gives us SERP results with snippets that
*contain* the matched text. So a CFO commenting 'we left Chargebee for
Zenskar last quarter' inside someone else's thread shows up here even
though no Reddit-native search would surface it.

Optional source — gracefully no-ops without a SERPER_API_KEY env var so
the pipeline stays runnable without it. Set the key as a GitHub secret
to unlock.
"""
import os
import re
import time
from datetime import datetime, timezone

import requests

from models import RedditHit

_API = "https://google.serper.dev/search"
_INTER_CALL = 0.4

# Pull the Reddit post ID out of a result URL. Same logic as the RSS
# extractor in sources/rss.py — kept local to avoid a circular import
# and because serper.dev returns canonical URLs we can trust.
_POST_ID_RE = re.compile(r"/r/([^/]+)/comments/([a-z0-9]+)/")


def _parse_reddit_url(url: str) -> tuple[str, str] | None:
    m = _POST_ID_RE.search(url)
    if not m:
        return None
    return m.group(1), m.group(2)  # (subreddit, post_id_short)


def _is_configured() -> bool:
    return bool(os.environ.get("SERPER_API_KEY"))


def _result_to_hit(result: dict, query: str) -> RedditHit | None:
    url = result.get("link") or ""
    parsed = _parse_reddit_url(url)
    if not parsed:
        return None
    sub, short_id = parsed
    title = (result.get("title") or "").strip()
    snippet = (result.get("snippet") or "").strip()
    if not title:
        return None
    # Date is best-effort; Serper returns it for some result types only.
    ts = datetime.now(timezone.utc)
    return RedditHit(
        post_id=f"t3_{short_id}",
        subreddit=sub,
        author=None,
        title=title,
        # Body holds the SERP snippet — often contains the actual matched
        # body/comment text, which is the whole point of this source.
        body=snippet or None,
        permalink=url,
        created_utc=ts,
        score=None,
        num_comments=None,
        source="google_reddit",
        matched_keywords=[query],
    )


def search(query: str, num: int = 10) -> list[RedditHit]:
    """Run one site-restricted Google query via serper.dev. The site:
    operator is appended here so callers don't have to repeat it."""
    if not _is_configured():
        return []
    payload = {"q": f'site:reddit.com "{query}"', "num": num}
    try:
        resp = requests.post(
            _API,
            headers={
                "X-API-KEY": os.environ["SERPER_API_KEY"],
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[google_reddit] query {query!r} failed: {e}")
        return []
    out: list[RedditHit] = []
    for result in data.get("organic", []) or []:
        hit = _result_to_hit(result, query)
        if hit is not None:
            out.append(hit)
    return out


def fetch_all(queries: list[str], max_queries: int) -> list[RedditHit]:
    if not _is_configured():
        print("[google_reddit] SERPER_API_KEY not set — skipping (set it to unlock 5-10x coverage)")
        return []
    merged: dict[str, RedditHit] = {}
    used = 0
    for q in queries:
        if used >= max_queries:
            break
        for hit in search(q):
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
