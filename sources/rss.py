import os
import random
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
_INTER_CALL_MIN = 1.0  # jittered delay between RSS fetches; defeats deterministic cadence detection
_INTER_CALL_MAX = 2.5
# Cap each retry sleep. Reddit started blanket-429ing the unauthenticated
# search.rss endpoint (~June 2026); with unbounded exponential backoff across
# ~50 endpoints the discovery sweep ran past the CI job's 30-min timeout and
# the whole run was cancelled before writing anything. The cap + the wall-clock
# budget below keep the sweep bounded so the run always finishes and reaches
# the other (non-Reddit) sources.
_MAX_BACKOFF_SEC = 8.0
_DISCOVERY_BUDGET_SEC = float(os.environ.get("RSS_DISCOVERY_BUDGET_SEC", "480"))

# Browser-like headers beyond just UA reduce the chance Cloudflare flags the
# request as a scraper. Connection: close forces a fresh TCP each call, which
# counter-intuitively looks less like one long-lived scraper session.
_BASE_HEADERS = {
    "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.1",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Connection": "close",
}


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


def _headers() -> dict[str, str]:
    return {"User-Agent": _ua(), **_BASE_HEADERS}


def _is_connection_reset(exc: BaseException) -> bool:
    """Walk the exception chain looking for a TCP-level reset. Cloudflare
    returns these when it has flagged the caller; retrying many times in a row
    reinforces the bot reputation and makes recovery slower."""
    cur = exc
    while cur is not None:
        if isinstance(cur, ConnectionResetError):
            return True
        msg = str(cur).lower()
        if "forcibly closed" in msg or "connection reset" in msg or "connection aborted" in msg:
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _fetch_feed(url: str, max_retries: int = 3, deadline: float | None = None) -> list:
    """Fetch via requests so we control headers, detect Reddit's anti-bot
    HTML interstitial (status 200 + HTML body), and retry with bounded backoff.
    On TCP resets we fail fast (one retry) since Cloudflare's IP-level block
    won't clear in seconds — the next cron tick or a fresh CI runner IP will.

    `deadline` is a time.monotonic() timestamp shared across the whole
    discovery sweep: if a backoff would push past it we give up on this URL
    immediately rather than sleeping. This is what stops a 429 storm from
    consuming the entire CI budget — better to skip the rest of Reddit and
    let the other sources run than to time out and write nothing."""
    delay = 3.0
    reset_retries_used = 0

    def _backoff(wait: float) -> bool:
        """Sleep `wait` (capped at _MAX_BACKOFF_SEC). Returns False — meaning
        'give up now' — if the shared deadline would be exceeded."""
        wait = min(wait, _MAX_BACKOFF_SEC)
        if deadline is not None and time.monotonic() + wait > deadline:
            return False
        time.sleep(wait)
        return True

    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                headers=_headers(),
                timeout=20,
                allow_redirects=True,
            )
        except Exception as e:
            if _is_connection_reset(e):
                reset_retries_used += 1
                if reset_retries_used > 1:
                    print(f"[rss] persistent TCP reset on {url}; giving up (IP likely flagged)")
                    return []
                if not _backoff(random.uniform(5, 10)):
                    return []
                print(f"[rss] connection reset on {url}: {e} (retried)")
                continue
            print(f"[rss] request error on {url}: {e}")
            if not _backoff(delay + random.uniform(0, delay)):
                return []
            delay *= 2
            continue

        if resp.status_code in (429, 503):
            print(f"[rss] {resp.status_code} on {url}; backing off")
            if not _backoff(delay + random.uniform(0, delay)):
                print(f"[rss] {resp.status_code} budget hit on {url}; skipping (other sources still run)")
                return []
            delay *= 2
            continue

        if _looks_like_html(resp.text):
            print(f"[rss] HTML interstitial on {url} (likely bot detection); backing off")
            if not _backoff(delay + random.uniform(0, delay)):
                return []
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


def fetch_subreddit_new(subreddit: str, deadline: float | None = None) -> list[RedditHit]:
    url = _SUB_URL.format(sub=subreddit)
    hits: list[RedditHit] = []
    for entry in _fetch_feed(url, deadline=deadline):
        hit = _entry_to_hit(entry, source="rss_sub", fallback_sub=subreddit, matched=[])
        if hit:
            hits.append(hit)
    return hits


def fetch_search(keyword: str, deadline: float | None = None) -> list[RedditHit]:
    """Global keyword search; post-filter for exact keyword since Reddit's
    tokeniser returns loose matches."""
    url = _SEARCH_URL.format(q=quote(keyword))
    keyword_lower = keyword.lower()
    hits: list[RedditHit] = []
    for entry in _fetch_feed(url, deadline=deadline):
        title = getattr(entry, "title", "") or ""
        summary = _strip_html(getattr(entry, "summary", ""))
        haystack = f"{title}\n{summary}".lower()
        if keyword_lower not in haystack:
            continue
        hit = _entry_to_hit(entry, source="rss_search", fallback_sub=None, matched=[keyword])
        if hit:
            hits.append(hit)
    return hits


def _inter_call_sleep() -> None:
    time.sleep(random.uniform(_INTER_CALL_MIN, _INTER_CALL_MAX))


def fetch_all(subreddits: list[str], keywords: list[str]) -> list[RedditHit]:
    """Fetch both layers of discovery and merge by post_id, union matched keywords.
    Jittered inter-call delay breaks the deterministic-cadence signal Cloudflare
    uses to flag scraping traffic."""
    merged: dict[str, RedditHit] = {}
    endpoints = len(subreddits) + len(keywords)
    deadline = time.monotonic() + _DISCOVERY_BUDGET_SEC
    idx = 0
    skipped = 0
    for sub in subreddits:
        if time.monotonic() > deadline:
            skipped = endpoints - idx
            break
        for hit in fetch_subreddit_new(sub, deadline=deadline):
            if hit.post_id not in merged:
                merged[hit.post_id] = hit
        idx += 1
        if idx < endpoints:
            _inter_call_sleep()
    for kw in keywords:
        if time.monotonic() > deadline:
            skipped = endpoints - idx
            break
        for hit in fetch_search(kw, deadline=deadline):
            existing = merged.get(hit.post_id)
            if existing is None:
                merged[hit.post_id] = hit
            else:
                for k in hit.matched_keywords:
                    if k not in existing.matched_keywords:
                        existing.matched_keywords.append(k)
        idx += 1
        if idx < endpoints:
            _inter_call_sleep()
    if skipped:
        print(f"[rss] discovery budget ({_DISCOVERY_BUDGET_SEC:.0f}s) exhausted; "
              f"skipped {skipped}/{endpoints} endpoints — other sources still run")
    return list(merged.values())
