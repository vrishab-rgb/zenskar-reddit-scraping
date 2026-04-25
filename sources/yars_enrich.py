"""Reddit post + user enrichment via the official OAuth API.

Was originally built on the vendored YARS scraper hitting www.reddit.com
.json endpoints unauthenticated — Reddit started blocking that pattern
from datacenter IPs (e.g. GitHub Actions) in 2023. Switched to OAuth +
oauth.reddit.com via `sources.reddit_oauth`. Public surface is unchanged:
`fetch_post`, `fetch_user_hints`, `enrich` keep their signatures so
`main.py` and the digest renderer don't need to know.
"""
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

import db
from config import COMPETITORS, ICP_SUBS, YARS_MIN_INTERVAL_SECONDS
from models import Comment, EnrichedHit, RedditHit, UserHints
from sources import reddit_oauth

_lock = threading.Lock()
_last_call_at = 0.0

_OAUTH_BASE = "https://oauth.reddit.com"


def _throttle() -> None:
    """Global rate limiter: block until YARS_MIN_INTERVAL_SECONDS has passed
    since the previous call. Reddit's authed limit is ~100 req/min; we keep
    the same conservative 6s spacing because comment+user fetches each
    burst 3 calls per post and we don't want to chew quota."""
    global _last_call_at
    with _lock:
        wait = YARS_MIN_INTERVAL_SECONDS - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _permalink_path(permalink: str) -> str:
    """Reddit OAuth expects a path like '/r/sub/comments/xyz/'. Accept
    full URLs too."""
    if permalink.startswith("http"):
        return urlparse(permalink).path
    return permalink


def _get(url: str, params: dict | None = None) -> requests.Response | None:
    """Single-attempt GET against oauth.reddit.com with bearer auth.
    Returns None on auth failure or non-200; the caller decides how to
    degrade (most paths fall back to RSS-only enrichment)."""
    try:
        return requests.get(
            url,
            headers=reddit_oauth.auth_headers(),
            params=params or {},
            timeout=15,
        )
    except reddit_oauth.RedditAuthError as e:
        print(f"[reddit] auth failed (set REDDIT_CLIENT_ID/SECRET/USERNAME/PASSWORD): {e}")
        return None
    except Exception as e:
        print(f"[reddit] GET {url} error: {e}")
        return None


def _extract_comments(children) -> list[dict]:
    """Walk Reddit's nested t1 comment listing into a flat dict shape that
    `_comments_from_yars` knows how to consume. We don't recurse into
    replies — top-level signal is enough for classification."""
    out: list[dict] = []
    for c in children or []:
        if isinstance(c, dict) and c.get("kind") == "t1":
            d = c.get("data", {}) or {}
            score = d.get("score")
            if not isinstance(score, int):
                score = None
            out.append({
                "author": d.get("author") or "",
                "body": d.get("body") or "",
                "score": score,
            })
    return out


def fetch_post(permalink: str) -> dict | None:
    """GET the post .json via oauth.reddit.com. Returns
    {title, body, comments} on success, None on any failure."""
    _throttle()
    path = _permalink_path(permalink).rstrip("/")
    url = f"{_OAUTH_BASE}{path}.json"
    resp = _get(url)
    if resp is None or resp.status_code != 200:
        status = resp.status_code if resp is not None else "no-response"
        print(f"[reddit] fetch_post {permalink}: status={status}")
        return None
    try:
        data = resp.json()
    except ValueError:
        print(f"[reddit] fetch_post {permalink}: bad JSON")
        return None
    if not isinstance(data, list) or len(data) < 2:
        return None
    try:
        main_post = data[0]["data"]["children"][0]["data"]
    except (KeyError, IndexError, TypeError):
        return None
    return {
        "title": main_post.get("title", ""),
        "body": main_post.get("selftext", "") or "",
        "comments": _extract_comments(data[1].get("data", {}).get("children", [])),
    }


def _fetch_about(username: str) -> dict | None:
    _throttle()
    url = f"{_OAUTH_BASE}/user/{username}/about"
    resp = _get(url)
    if resp is None or resp.status_code != 200:
        return None
    try:
        return resp.json().get("data")
    except ValueError:
        return None


def _fetch_user_activity(username: str, limit: int = 50) -> list[dict]:
    """Recent posts + comments from this user. Same shape as the legacy
    YARS dict so downstream parsing is unchanged."""
    _throttle()
    url = f"{_OAUTH_BASE}/user/{username}/.json"
    resp = _get(url, params={"limit": limit})
    if resp is None or resp.status_code != 200:
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    items = data.get("data", {}).get("children", []) or []
    out: list[dict] = []
    for item in items:
        kind = item.get("kind")
        d = item.get("data", {}) or {}
        sub = d.get("subreddit", "") or ""
        if kind == "t3":
            out.append({"title": d.get("title", "") or "", "subreddit": sub, "body": ""})
        elif kind == "t1":
            out.append({"title": "", "subreddit": sub, "body": d.get("body", "") or ""})
    return out


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
    """Fetch full post body + top-level comments + user hints. On any
    failure, return EnrichedHit with enrichment_failed=True so the caller
    can fall back to RSS-only classification."""
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
