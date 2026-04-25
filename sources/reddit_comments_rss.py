"""Reddit /comments/.rss feed per ICP subreddit.

The regular sub RSS only gives us new POSTS. This module pulls the
comments-only RSS (Reddit exposes /r/<sub>/comments/.rss as a separate
feed) so we catch in-thread mentions: a CFO replying 'yeah we left
Chargebee for similar reasons' in someone else's thread is invisible to
the post-only feeds. Filtered post-fetch by keyword presence — Reddit
doesn't let us search comments via RSS.

Each matching comment is normalized to a RedditHit with the COMMENT'S
URL as permalink (so Slack alerts deep-link straight to the comment),
and the post_id namespaced as 't1_<comment_id>' — distinct from the
'_t3_' post namespace, so a post AND its comment can both alert
without collision.
"""
import random
import re
import time
from calendar import timegm
from datetime import datetime, timezone

from sources.rss import (
    _BASE_HEADERS,
    _entry_datetime,
    _fetch_feed,
    _strip_html,
    _ua,
)
from models import RedditHit

_COMMENTS_URL = "https://www.reddit.com/r/{sub}/comments/.rss"

# Comment permalinks look like:
#   /r/<sub>/comments/<post_id>/<slug>/<comment_id>/
_COMMENT_ID_RE = re.compile(r"/r/[^/]+/comments/[^/]+/[^/]+/([a-z0-9]+)/?")


def _comment_id_from_link(link: str) -> str | None:
    m = _COMMENT_ID_RE.search(link)
    return m.group(1) if m else None


def _entry_to_hit(entry, sub: str, matched: list[str]) -> RedditHit | None:
    link = getattr(entry, "link", None)
    if not link:
        return None
    cid = _comment_id_from_link(link)
    if not cid:
        return None
    body = _strip_html(getattr(entry, "summary", "")) or None
    author = getattr(entry, "author", None)
    if author and author.startswith("/u/"):
        author = author[3:]
    return RedditHit(
        # t1_ namespace so a comment doesn't collide with its parent post (t3_).
        post_id=f"t1_{cid}",
        subreddit=sub,
        author=author,
        title=getattr(entry, "title", "") or "(comment)",
        body=body,
        permalink=link,
        created_utc=_entry_datetime(entry),
        score=None,
        num_comments=None,
        source="reddit_comments_rss",
        matched_keywords=matched,
    )


def fetch_subreddit_comments(sub: str, keywords: list[str]) -> list[RedditHit]:
    """Pull the comments feed for one sub. Post-filter by keyword presence in
    title or body. Reddit doesn't expose comment search, so we have to do
    the matching client-side — cheap, since each feed is small."""
    keywords_lower = {k.lower() for k in keywords}
    url = _COMMENTS_URL.format(sub=sub)
    out: list[RedditHit] = []
    for entry in _fetch_feed(url):
        title = getattr(entry, "title", "") or ""
        summary = _strip_html(getattr(entry, "summary", ""))
        haystack = f"{title}\n{summary}".lower()
        matched = [k for k in keywords_lower if k in haystack]
        if not matched:
            continue
        # Re-canonicalize matched against original casing so downstream
        # logs/competitor lookups stay readable.
        canon = [k for k in keywords if k.lower() in matched]
        hit = _entry_to_hit(entry, sub, matched=canon)
        if hit:
            out.append(hit)
    return out


def fetch_all(subreddits: list[str], keywords: list[str], max_feeds: int) -> list[RedditHit]:
    """One feed per subreddit, up to max_feeds. Inter-call jitter avoids
    looking like deterministic scraping traffic."""
    merged: dict[str, RedditHit] = {}
    used = 0
    for sub in subreddits:
        if used >= max_feeds:
            break
        for hit in fetch_subreddit_comments(sub, keywords):
            existing = merged.get(hit.post_id)
            if existing is None:
                merged[hit.post_id] = hit
            else:
                for k in hit.matched_keywords:
                    if k not in existing.matched_keywords:
                        existing.matched_keywords.append(k)
        used += 1
        if used < max_feeds:
            time.sleep(random.uniform(1.0, 2.5))
    return list(merged.values())
