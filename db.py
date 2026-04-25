import os
from datetime import datetime, timedelta, timezone

import requests

from config import USER_HINT_TTL_DAYS
from models import Classification, CommentSuggestion, RedditHit, UserHints

_session = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        key = os.environ["SUPABASE_KEY"]
        _session.headers.update({
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })
    return _session


def _url(path: str) -> str:
    return f"{os.environ['SUPABASE_URL']}/rest/v1/{path}"


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def is_seen(post_id: str) -> bool:
    try:
        resp = _get_session().get(
            _url("reddit_hits"),
            params={"post_id": f"eq.{post_id}", "select": "post_id"},
            timeout=30,
        )
        resp.raise_for_status()
        return len(resp.json()) > 0
    except Exception as e:
        print(f"[db] is_seen error: {e}")
        return False


def upsert_hit(hit: RedditHit) -> None:
    payload = {
        "post_id": hit.post_id,
        "created_utc": _iso(hit.created_utc),
        "subreddit": hit.subreddit,
        "author": hit.author,
        "title": hit.title,
        "body": hit.body,
        "permalink": hit.permalink,
        "score": hit.score,
        "num_comments": hit.num_comments,
        "source": hit.source,
        "matched_keywords": hit.matched_keywords,
    }
    try:
        resp = _get_session().post(
            _url("reddit_hits"),
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[db] upsert_hit error for {hit.post_id}: {e}")


def record_classification(cls: Classification) -> None:
    payload = {
        "post_id": cls.post_id,
        "bucket": cls.bucket,
        "mentioned_competitors": cls.mentioned_competitors,
        "buyer_persona_hint": cls.buyer_persona_hint,
        "company_size_hint": cls.company_size_hint,
        "pain_points": cls.pain_points,
        "sentiment": cls.sentiment,
        "prompt_version": cls.prompt_version,
    }
    try:
        resp = _get_session().post(
            _url("reddit_classifications"),
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[db] record_classification error for {cls.post_id}: {e}")


def record_comment_suggestion(s: CommentSuggestion) -> None:
    payload = {
        "post_id": s.post_id,
        "suggested_comment": s.suggested_comment,
        "plug_strategy": s.plug_strategy,
        "rationale": s.rationale,
        "skip_reason": s.skip_reason,
        "prompt_version": s.prompt_version,
    }
    try:
        resp = _get_session().post(
            _url("reddit_comment_suggestions"),
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[db] record_comment_suggestion error for {s.post_id}: {e}")


def was_alerted(post_id: str) -> bool:
    try:
        resp = _get_session().get(
            _url("reddit_alerted"),
            params={"post_id": f"eq.{post_id}", "select": "post_id"},
            timeout=30,
        )
        resp.raise_for_status()
        return len(resp.json()) > 0
    except Exception as e:
        print(f"[db] was_alerted error: {e}")
        return False


def mark_alerted(post_id: str, bucket: str, slack_channel: str) -> None:
    try:
        resp = _get_session().post(
            _url("reddit_alerted"),
            json={
                "post_id": post_id,
                "bucket": bucket,
                "slack_channel": slack_channel,
            },
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[db] mark_alerted error for {post_id}: {e}")


def get_groq_tokens_used_today(model: str) -> int:
    """Return tokens already consumed today (UTC) for `model`, or 0 if no row."""
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        resp = _get_session().get(
            _url("groq_daily_usage"),
            params={
                "model": f"eq.{model}",
                "day_utc": f"eq.{today}",
                "select": "tokens_used",
            },
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        return int(rows[0]["tokens_used"]) if rows else 0
    except Exception as e:
        print(f"[db] get_groq_tokens_used_today error for {model}: {e}")
        return 0


def add_groq_tokens_used(model: str, additional: int) -> None:
    """Read-then-write increment of today's row. Safe because the monitor
    workflow has concurrency=cancel-in-progress:false (single instance at
    a time). Runs once per cron tick at end-of-run, so the race window is
    tiny even if that assumption ever loosens."""
    if additional <= 0:
        return
    today = datetime.now(timezone.utc).date().isoformat()
    current = get_groq_tokens_used_today(model)
    payload = {
        "model": model,
        "day_utc": today,
        "tokens_used": current + additional,
        "updated_at": _iso(datetime.now(timezone.utc)),
    }
    try:
        resp = _get_session().post(
            _url("groq_daily_usage"),
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[db] add_groq_tokens_used error for {model}: {e}")


def get_user_hints(username: str) -> UserHints | None:
    """Return cached hints if fetched within TTL, else None."""
    try:
        resp = _get_session().get(
            _url("reddit_user_hints"),
            params={"username": f"eq.{username}", "select": "*"},
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            return None
        row = rows[0]
        fetched_at = datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
        if datetime.now(timezone.utc) - fetched_at > timedelta(days=USER_HINT_TTL_DAYS):
            return None
        return UserHints(
            username=row["username"],
            recent_subreddits=row.get("recent_subreddits") or [],
            account_age_days=row.get("account_age_days"),
            total_karma=row.get("total_karma"),
            prior_competitor_mentions=row.get("prior_competitor_mentions") or [],
            is_icp_likely=bool(row.get("is_icp_likely")),
        )
    except Exception as e:
        print(f"[db] get_user_hints error for {username}: {e}")
        return None


def upsert_user_hints(hints: UserHints) -> None:
    payload = {
        "username": hints.username,
        "fetched_at": _iso(datetime.now(timezone.utc)),
        "recent_subreddits": hints.recent_subreddits,
        "account_age_days": hints.account_age_days,
        "total_karma": hints.total_karma,
        "prior_competitor_mentions": hints.prior_competitor_mentions,
        "is_icp_likely": hints.is_icp_likely,
    }
    try:
        resp = _get_session().post(
            _url("reddit_user_hints"),
            json=payload,
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[db] upsert_user_hints error for {hints.username}: {e}")
