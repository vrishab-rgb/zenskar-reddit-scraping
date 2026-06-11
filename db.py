import os
from datetime import datetime, timedelta, timezone

import requests

from config import USER_HINT_TTL_DAYS
from models import Classification, RedditHit, UserHints

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


# --- Engagement drafts + engaged state --------------------------------------
# Read by the CI drafter (draft_comments.py) and the local poster (poster/).
# Unlike the monitor's swallow-and-print error style, draft state transitions
# RAISE on failure: the poster must never submit a comment it couldn't first
# claim in the DB (double-post protection), so a silent DB failure is unsafe.

# Embedded !inner join: unclassified hits are excluded by the DB, and the
# bucket filter below removes noise before the limit applies.
_DRAFT_CANDIDATE_FIELDS = (
    "post_id, subreddit, title, permalink, created_utc, source, "
    "reddit_classifications!inner(bucket, pain_points, mentioned_competitors)"
)


def get_recent_classified(lookback_hours: int, max_rows: int = 120) -> list[dict]:
    """Recent non-noise classified hits for draft selection."""
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(hours=lookback_hours))
    try:
        resp = _get_session().get(
            _url("reddit_hits"),
            params={
                "select": _DRAFT_CANDIDATE_FIELDS,
                "created_utc": f"gte.{cutoff}",
                "reddit_classifications.bucket": "neq.noise",
                "order": "created_utc.desc",
                "limit": str(max_rows),
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[db] get_recent_classified error: {e}")
        return []


def get_engaged() -> tuple[set[str], set[str]]:
    """(engaged post_ids, engaged thread_ids) — shared state with the MCP
    server's reddit_engagement_candidates tool."""
    try:
        resp = _get_session().get(
            _url("reddit_engaged"),
            params={"select": "post_id,thread_id"},
            timeout=30,
        )
        resp.raise_for_status()
        rows = resp.json()
        return (
            {r["post_id"] for r in rows},
            {r["thread_id"] for r in rows if r.get("thread_id")},
        )
    except Exception as e:
        print(f"[db] get_engaged error: {e}")
        return set(), set()


def mark_engaged(post_id: str, thread_id: str, comment_url: str = "", note: str = "") -> None:
    """Upsert into reddit_engaged so the candidate stops re-surfacing (both
    here and in the MCP tool). Mirrors mcp_server/clients/reddit.py."""
    try:
        resp = _get_session().post(
            _url("reddit_engaged"),
            json={
                "post_id": post_id,
                "thread_id": thread_id,
                "comment_url": comment_url or None,
                "note": note or None,
                "engaged_at": _iso(datetime.now(timezone.utc)),
            },
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[db] mark_engaged error for {post_id}: {e}")


def get_drafted_ids() -> set[str]:
    """All post_ids that ever got a draft row (any status) — drafting is
    one-shot per candidate."""
    try:
        resp = _get_session().get(
            _url("reddit_drafts"),
            params={"select": "post_id", "order": "created_at.desc", "limit": "2000"},
            timeout=30,
        )
        resp.raise_for_status()
        return {r["post_id"] for r in resp.json()}
    except Exception as e:
        print(f"[db] get_drafted_ids error: {e}")
        # Fail CLOSED: returning a fake empty set would re-draft (and re-send
        # to Telegram) everything. Raising aborts the drafter run instead.
        raise


def insert_draft(row: dict) -> None:
    resp = _get_session().post(
        _url("reddit_drafts"),
        json=row,
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        timeout=30,
    )
    resp.raise_for_status()


def update_draft(post_id: str, fields: dict) -> None:
    """PATCH a draft row. Raises on failure — callers rely on state
    transitions actually landing (see module comment)."""
    fields = {**fields, "updated_at": _iso(datetime.now(timezone.utc))}
    resp = _get_session().patch(
        _url("reddit_drafts"),
        params={"post_id": f"eq.{post_id}"},
        json=fields,
        headers={"Prefer": "return=minimal"},
        timeout=30,
    )
    resp.raise_for_status()


def get_drafts_by_status(status: str) -> list[dict]:
    resp = _get_session().get(
        _url("reddit_drafts"),
        params={"status": f"eq.{status}", "select": "*", "order": "created_at.asc"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_draft_by_telegram_message(message_id: int) -> dict | None:
    resp = _get_session().get(
        _url("reddit_drafts"),
        params={"telegram_message_id": f"eq.{message_id}", "select": "*"},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def get_draft(post_id: str) -> dict | None:
    resp = _get_session().get(
        _url("reddit_drafts"),
        params={"post_id": f"eq.{post_id}", "select": "*"},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows[0] if rows else None


def count_posted_last_24h() -> int:
    cutoff = _iso(datetime.now(timezone.utc) - timedelta(hours=24))
    resp = _get_session().get(
        _url("reddit_drafts"),
        params={
            "status": "eq.posted",
            "posted_at": f"gte.{cutoff}",
            "select": "post_id",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return len(resp.json())


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
