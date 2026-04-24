import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import db
from config import COMPETITORS, ICP_SUBS, YARS_MIN_INTERVAL_SECONDS
from models import Comment, EnrichedHit, RedditHit, UserHints

_yars_client = None
_lock = threading.Lock()
_last_call_at = 0.0

_ABOUT_URL = "https://www.reddit.com/user/{u}/about.json"
_DEFAULT_UA = "zenskar-marketing-monitor/1.0 (contact: priyam.s@zenskar.com)"


def _ua() -> str:
    return os.environ.get("REDDIT_RSS_USER_AGENT", _DEFAULT_UA)


def _get_client():
    global _yars_client
    if _yars_client is None:
        from yars.yars import YARS
        _yars_client = YARS()
    return _yars_client


def _throttle() -> None:
    """Global rate limiter: block until YARS_MIN_INTERVAL_SECONDS has passed
    since the previous call. Reddit's unauthenticated .json ceiling is ~10/min;
    we pace at ~10/min with headroom."""
    global _last_call_at
    with _lock:
        wait = YARS_MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _permalink_path(permalink: str) -> str:
    """YARS expects a path like '/r/sub/comments/xyz/'. Accept full URLs too."""
    if permalink.startswith("http"):
        return urlparse(permalink).path
    return permalink


def fetch_post(permalink: str) -> dict | None:
    _throttle()
    try:
        return _get_client().scrape_post_details(_permalink_path(permalink))
    except Exception as e:
        print(f"[yars] fetch_post error for {permalink}: {e}")
        return None


def _fetch_about(username: str) -> dict | None:
    _throttle()
    try:
        resp = requests.get(
            _ABOUT_URL.format(u=username),
            headers={"User-Agent": _ua()},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return resp.json().get("data")
    except Exception as e:
        print(f"[yars] fetch_about error for {username}: {e}")
        return None


def _fetch_user_activity(username: str, limit: int = 50) -> list[dict]:
    _throttle()
    try:
        items = _get_client().scrape_user_data(username, limit=limit)
        return items or []
    except Exception as e:
        print(f"[yars] scrape_user_data error for {username}: {e}")
        return []


def fetch_user_hints(username: str) -> UserHints | None:
    if not username:
        return None
    cached = db.get_user_hints(username)
    if cached is not None:
        return cached

    activity = _fetch_user_activity(username)
    about = _fetch_about(username)
    if not activity and not about:
        return None

    sub_counter: Counter[str] = Counter()
    mentioned: set[str] = set()
    competitors_lower = {c.lower(): c for c in COMPETITORS}

    for item in activity:
        sub = (item.get("subreddit") or "").strip()
        if sub:
            sub_counter[sub] += 1
        haystack = f"{item.get('title', '')} {item.get('body', '')}".lower()
        for lower, canonical in competitors_lower.items():
            if lower in haystack:
                mentioned.add(canonical)

    recent_subs = [s for s, _ in sub_counter.most_common(5)]
    icp_set_lower = {s.lower() for s in ICP_SUBS}
    is_icp_likely = any(s.lower() in icp_set_lower for s in recent_subs)

    account_age_days: int | None = None
    total_karma: int | None = None
    if about:
        created = about.get("created_utc")
        if created:
            created_dt = datetime.fromtimestamp(float(created), tz=timezone.utc)
            account_age_days = (datetime.now(timezone.utc) - created_dt).days
        total_karma = about.get("total_karma")

    hints = UserHints(
        username=username,
        recent_subreddits=recent_subs,
        account_age_days=account_age_days,
        total_karma=total_karma,
        prior_competitor_mentions=sorted(mentioned),
        is_icp_likely=is_icp_likely,
    )
    db.upsert_user_hints(hints)
    return hints


def _comments_from_yars(raw: list[dict]) -> list[Comment]:
    out: list[Comment] = []
    for c in raw or []:
        score = c.get("score")
        if not isinstance(score, int):
            score = None
        out.append(Comment(
            author=c.get("author") or None,
            body=c.get("body", "") or "",
            score=score,
        ))
    return out


def enrich(hit: RedditHit) -> EnrichedHit:
    """Fetch full post body + top-level comments + user hints.
    On any failure, return EnrichedHit with enrichment_failed=True so the
    caller can fall back to RSS-only classification."""
    post = fetch_post(hit.permalink)
    if post is None:
        return EnrichedHit(hit=hit, enrichment_failed=True)

    if post.get("body") and not hit.body:
        hit.body = post["body"]

    comments = _comments_from_yars(post.get("comments", []))
    user_hints = fetch_user_hints(hit.author) if hit.author else None

    return EnrichedHit(
        hit=hit,
        comments=comments,
        user_hints=user_hints,
        enrichment_failed=False,
    )
