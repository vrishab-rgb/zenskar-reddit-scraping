"""Candidate selection for the drafter.

Mirrors the ranking/dedup logic in the MCP server's reddit client
(zenskar-mcp-server/mcp_server/clients/reddit.py) so the automated drafting
queue and the manual `reddit_engagement_candidates` tool agree on what's
worth engaging next: bucket priority, newest first, one candidate per thread,
one per normalized title (crossposts), nothing already engaged or drafted.
"""

import re
from datetime import datetime, timezone

from config import (
    ENGAGE_EXCLUDE_COMPETITORS,
    MAX_CANDIDATE_AGE_HOURS,
    MUSIC_SUBS,
    TABS_BILLING_CONTEXT_TOKENS,
)

# Reddit comment permalinks look like /r/<sub>/comments/<submission>/<slug>/<comment>/
_THREAD_RE = re.compile(r"/comments/([a-z0-9]+)")

# Higher = drafted first. 'noise' never reaches selection (DB-side filter).
_BUCKET_PRIORITY = {
    "lead_signal": 3,
    "competitor_mention": 2,
    "icp_discussion": 1,
}


def thread_id(post_id: str, permalink: str = "") -> str:
    """The submission (thread) id a candidate belongs to. A post's id IS the
    thread (t3_<submission>); a comment's thread is parsed from its permalink
    so a post and its comments collapse to the same thread."""
    if post_id.startswith("t3_"):
        return post_id[3:]
    m = _THREAD_RE.search(permalink or "")
    return m.group(1) if m else post_id


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _classification(row: dict) -> dict | None:
    """PostgREST embeds the 1:1 classification as either an object or a
    1-element list depending on relationship detection. Normalize to a dict."""
    c = row.get("reddit_classifications")
    if isinstance(c, list):
        c = c[0] if c else None
    return c or None


def _age_hours(created_utc: str | None) -> float | None:
    if not created_utc:
        return None
    try:
        created = datetime.fromisoformat(created_utc.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600


def _tabs_is_noise(subreddit: str, title: str, competitors: list[str]) -> bool:
    """True when the only competitor angle is 'Tabs' and nothing in the title
    grounds it in billing — i.e. it's probably guitar/browser/spreadsheet tabs."""
    comps = {c.lower() for c in competitors}
    if comps != {"tabs"}:
        return False
    t = title.lower()
    return not any(tok in t for tok in TABS_BILLING_CONTEXT_TOKENS)


def shape(row: dict) -> dict | None:
    """Flatten a hit+classification row into a candidate dict. Returns None for
    rows we will not engage on: noise/unclassified, non-Reddit sources, stale
    threads, music-sub guitar-tab noise, and competitor angles we exclude from
    engagement (e.g. Stripe Billing). Intel capture upstream is unaffected; this
    only governs what we draft a comment on."""
    cls = _classification(row)
    if cls is None:
        return None
    bucket = cls.get("bucket")
    if not bucket or bucket == "noise":
        return None
    permalink = row.get("permalink") or ""
    if "reddit.com" not in permalink:
        return None

    # Freshness: engagement is worthless on a cold thread.
    age = _age_hours(row.get("created_utc"))
    if age is not None and age > MAX_CANDIDATE_AGE_HOURS:
        return None

    subreddit = row.get("subreddit") or ""
    title = row.get("title") or ""
    competitors = cls.get("mentioned_competitors") or []

    # QA guard: never draft on a music/instrument sub (guitar-tab false positive).
    if subreddit.lower() in MUSIC_SUBS:
        return None
    if _tabs_is_noise(subreddit, title, competitors):
        return None

    # Drop engagement-excluded competitors when that's the ONLY angle. If the
    # thread also names another competitor or is a lead/icp bucket, keep it.
    if competitors and {c.lower() for c in competitors} <= {
        c.lower() for c in ENGAGE_EXCLUDE_COMPETITORS
    } and bucket == "competitor_mention":
        return None

    post_id = row["post_id"]
    return {
        "post_id": post_id,
        "kind": "comment" if post_id.startswith("t1_") else "post",
        "subreddit": subreddit,
        "title": title,
        "permalink": permalink,
        "created_utc": row.get("created_utc"),
        "bucket": bucket,
        "pain_points": cls.get("pain_points") or [],
        "mentioned_competitors": competitors,
    }


def pick(
    rows: list[dict],
    engaged_ids: set[str],
    engaged_threads: set[str],
    drafted_ids: set[str],
    limit: int,
) -> list[dict]:
    """Rank, then keep one highest-ranked candidate per thread / normalized
    title, skipping anything already engaged or already drafted."""
    cands = [c for c in (shape(r) for r in rows) if c is not None]
    cands.sort(
        key=lambda c: (
            _BUCKET_PRIORITY.get(c["bucket"], 0),
            c["created_utc"] or "",
        ),
        reverse=True,
    )

    seen_threads = set(engaged_threads)
    seen_titles: set[str] = set()
    out: list[dict] = []
    for c in cands:
        tid = thread_id(c["post_id"], c["permalink"])
        title_key = _norm_title(c["title"])
        if c["post_id"] in engaged_ids or c["post_id"] in drafted_ids:
            continue
        if tid in seen_threads:
            continue
        if title_key and title_key in seen_titles:
            continue
        seen_threads.add(tid)
        if title_key:
            seen_titles.add(title_key)
        out.append(c)
        if len(out) >= limit:
            break
    return out
