"""Reddit /comments/.rss feed per ICP subreddit.

The regular sub RSS only gives us new POSTS. This module pulls the
comments-only RSS (Reddit exposes /r/<sub>/comments/.rss as a separate
feed) so we catch in-thread mentions: a CFO replying 'yeah we left
Chargebee for similar reasons' in someone else's thread is invisible to
the post-only feeds.

LESSON LEARNED: keyword-filtering comments by competitor name returns
~zero matches because comment bodies rarely mention the topic-word
('we left them' doesn't contain 'Chargebee' even when discussing
Chargebee). So we now stream ALL comments through to stage-1 from the
specific ICP subs we care about — let the LLM relevance filter decide.
The 18 ICP subs are themselves the topical pre-filter; everything in
r/CFO is at least loosely finance-relevant.

Each comment is normalized to a RedditHit with the COMMENT'S URL as
permalink (so Slack alerts deep-link straight to the comment), and the
post_id namespaced as 't1_<comment_id>' — distinct from the 't3_'
post namespace, so a post AND its comment can both alert without
collision.
"""
import os
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

# Wall-clock cap on the comments sweep, mirroring sources.rss. The comments
# feed hits the same www.reddit.com host that started 429ing, so it needs the
# same protection against blowing the CI timeout on a rate-limit storm.
_COMMENTS_BUDGET_SEC = float(os.environ.get("RSS_COMMENTS_BUDGET_SEC", "240"))

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


def fetch_subreddit_comments(
    sub: str, keywords: list[str] | None = None, deadline: float | None = None
) -> list[RedditHit]:
    """Pull the comments feed for one sub. We DON'T filter by keyword here
    anymore — comment bodies usually don't mention the topic-word, so
    keyword filtering produced ~zero hits. Streaming everything is fine
    because the 18 ICP subs are themselves the pre-filter. `keywords` is
    accepted for API compatibility but ignored."""
    url = _COMMENTS_URL.format(sub=sub)
    out: list[RedditHit] = []
    entries = _fetch_feed(url, deadline=deadline)
    for entry in entries:
        hit = _entry_to_hit(entry, sub, matched=[])
        if hit:
            out.append(hit)
    print(f"[reddit_comments] r/{sub}: {len(entries)} comments fetched, {len(out)} valid")
    return out


def fetch_all(subreddits: list[str], keywords: list[str] | None, max_feeds: int) -> list[RedditHit]:
    """One feed per subreddit, up to max_feeds. Inter-call jitter avoids
    looking like deterministic scraping traffic."""
    merged: dict[str, RedditHit] = {}
    deadline = time.monotonic() + _COMMENTS_BUDGET_SEC
    used = 0
    for sub in subreddits:
        if used >= max_feeds:
            break
        if time.monotonic() > deadline:
            print(f"[reddit_comments] budget ({_COMMENTS_BUDGET_SEC:.0f}s) exhausted "
                  f"after {used}/{max_feeds} feeds; moving on")
            break
        for hit in fetch_subreddit_comments(sub, keywords, deadline=deadline):
            existing = merged.get(hit.post_id)
            if existing is None:
                merged[hit.post_id] = hit
        used += 1
        if used < max_feeds:
            time.sleep(random.uniform(1.0, 2.5))
    return list(merged.values())
