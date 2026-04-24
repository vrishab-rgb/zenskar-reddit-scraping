import os
import re
import time
from calendar import timegm
from datetime import datetime, timezone
from urllib.parse import quote

import feedparser
import requests

from models import RedditHit

_SEARCH_URL = "https://www.reddit.com/search.rss?q={q}&sort=new&t=day"
_SUB_URL = "https://www.reddit.com/r/{sub}/new.rss"
_DEFAULT_UA = "zenskar-marketing-monitor/1.0 (contact: priyam.s@zenskar.com)"
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_INTER_CALL_DELAY = 0.75  # seconds between RSS fetches; avoids Reddit burst detection


def _ua() -> str:
    return os.environ.get("REDDIT_RSS_USER_AGENT", _DEFAULT_UA)


def _strip_html(s: str | None) -> str:
    if not s:
        return ""
    return _HTML_TAG_RE.sub(" ", s)


def _post_id_from_link(link: str) -> str | None:
    parts = link.rstrip("/").split("/")
    try:
        idx = parts.index("comments")
        return f"t3_{parts[idx + 1]}"
    except (ValueError, IndexError):
        return None


def _subreddit_from_link(link: str) -> str | None:
    parts = link.split("/")
    try:
        idx = parts.index("r")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return None


def _entry_datetime(entry) -> datetime:
    struct = getattr(entry, "updated_parsed", None) or getattr(entry, "published_parsed", None)
    if struct is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(timegm(struct), tz=timezone.utc)


def _looks_like_html(body: str) -> bool:
    head = body[:1000].lstrip().lower()
    return head.startswith("<!doctype html") or head.startswith("<html")


def _fetch_feed(url: str, max_retries: int = 3) -> list:
    """Fetch via requests so we control headers, detect Reddit's anti-bot
    HTML interstitial (status 200 + HTML body), and retry with backoff."""
    delay = 2.0
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": _ua(),
                    "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.1",
                },
                timeout=20,
                allow_redirects=True,
            )
        except Exception as e:
            print(f"[rss] request error on {url}: {e}")
            time.sleep(delay)
            delay *= 2
            continue

        if resp.status_code in (429, 503):
            print(f"[rss] {resp.status_code} on {url}; backing off {delay}s")
            time.sleep(delay)
            delay *= 2
            continue

        if _looks_like_html(resp.text):
            print(f"[rss] HTML interstitial on {url} (likely bot detection); backing off {delay}s")
            time.sleep(delay)
            delay *= 2
            continue

        result = feedparser.parse(resp.content)
        if getattr(result, "bozo", False) and not result.entries:
            print(f"[rss] parse failure on {url}: {getattr(result, 'bozo_exception', '')}")
            return []
        return result.entries
    print(f"[rss] giving up on {url} after {max_retries} retries")
    return []


def _entry_to_hit(entry, source: str, fallback_sub: str | None, matched: list[str]) -> RedditHit | None:
    link = getattr(entry, "link", None)
    if not link:
        return None
    post_id = _post_id_from_link(link)
    if not post_id:
        return None
    subreddit = fallback_sub or _subreddit_from_link(link) or "unknown"
    author = getattr(entry, "author", None)
    if author and author.startswith("/u/"):
        author = author[3:]
    summary = _strip_html(getattr(entry, "summary", ""))
    return RedditHit(
        post_id=post_id,
        subreddit=subreddit,
        author=author,
        title=getattr(entry, "title", "") or "",
        body=summary or None,
        permalink=link,
        created_utc=_entry_datetime(entry),
        score=None,
        num_comments=None,
        source=source,
        matched_keywords=matched,
    )


def fetch_subreddit_new(subreddit: str) -> list[RedditHit]:
    url = _SUB_URL.format(sub=subreddit)
    hits: list[RedditHit] = []
    for entry in _fetch_feed(url):
        hit = _entry_to_hit(entry, source="rss_sub", fallback_sub=subreddit, matched=[])
        if hit:
            hits.append(hit)
    return hits


def fetch_search(keyword: str) -> list[RedditHit]:
    """Global keyword search; post-filter for exact keyword since Reddit's
    tokeniser returns loose matches."""
    url = _SEARCH_URL.format(q=quote(keyword))
    keyword_lower = keyword.lower()
    hits: list[RedditHit] = []
    for entry in _fetch_feed(url):
        title = getattr(entry, "title", "") or ""
        summary = _strip_html(getattr(entry, "summary", ""))
        haystack = f"{title}\n{summary}".lower()
        if keyword_lower not in haystack:
            continue
        hit = _entry_to_hit(entry, source="rss_search", fallback_sub=None, matched=[keyword])
        if hit:
            hits.append(hit)
    return hits


def fetch_all(subreddits: list[str], keywords: list[str]) -> list[RedditHit]:
    """Fetch both layers of discovery and merge by post_id, union matched keywords.
    Paces calls with a short delay so Reddit doesn't flag the traffic as a burst."""
    merged: dict[str, RedditHit] = {}
    endpoints = len(subreddits) + len(keywords)
    idx = 0
    for sub in subreddits:
        for hit in fetch_subreddit_new(sub):
            if hit.post_id not in merged:
                merged[hit.post_id] = hit
        idx += 1
        if idx < endpoints:
            time.sleep(_INTER_CALL_DELAY)
    for kw in keywords:
        for hit in fetch_search(kw):
            existing = merged.get(hit.post_id)
            if existing is None:
                merged[hit.post_id] = hit
            else:
                for k in hit.matched_keywords:
                    if k not in existing.matched_keywords:
                        existing.matched_keywords.append(k)
        idx += 1
        if idx < endpoints:
            time.sleep(_INTER_CALL_DELAY)
    return list(merged.values())
