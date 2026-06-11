"""Fetch live thread context for a candidate via Reddit's public .json
endpoint. The pipeline's stored body is often just a search snippet
(google_reddit) or the comment text alone; the drafter needs the post plus
existing replies so it doesn't repeat what's already been said.

Uses the same UA/header posture as sources/rss.py — this runs from the same
GitHub Actions IP that already fetches Reddit RSS daily without issues.
"""

import os
import random
import time
from urllib.parse import urlparse

import requests

_DEFAULT_UA = "zenskar-marketing-monitor/1.0 (contact: priyam.s@zenskar.com)"
_INTER_CALL_MIN = 2.0
_INTER_CALL_MAX = 4.0
_MAX_TOP_COMMENTS = 8
_BODY_TRUNC = 2500
_COMMENT_TRUNC = 400

_last_call = 0.0


def _ua() -> str:
    return os.environ.get("REDDIT_RSS_USER_AGENT", _DEFAULT_UA)


def _throttle() -> None:
    global _last_call
    wait = _last_call + random.uniform(_INTER_CALL_MIN, _INTER_CALL_MAX) - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


def _json_url(permalink: str) -> str:
    """Normalize any reddit permalink (www/old, absolute/relative, with or
    without trailing slash) to an old.reddit .json URL."""
    parsed = urlparse(permalink)
    path = parsed.path if parsed.netloc else permalink
    path = path.rstrip("/")
    return f"https://old.reddit.com{path}.json?limit=30"


def _fmt_comment(c: dict, marker: str = "") -> str:
    body = (c.get("body") or "")[:_COMMENT_TRUNC]
    return f"- {marker}u/{c.get('author')} ({c.get('score', 0)} pts): {body}"


def _walk(children: list, out: list[dict]) -> None:
    """Flatten a comment tree depth-first; top-level order is preserved which
    is enough signal for 'what has already been said'."""
    for ch in children:
        if ch.get("kind") != "t1":
            continue
        data = ch.get("data") or {}
        out.append(data)
        replies = data.get("replies")
        if isinstance(replies, dict):
            _walk(replies.get("data", {}).get("children") or [], out)


def fetch_digest(permalink: str, kind: str, post_id: str) -> str | None:
    """Return a text digest of the thread (post + existing comments), or None
    when the fetch fails — the caller skips the candidate and it gets retried
    on the next run."""
    _throttle()
    try:
        resp = requests.get(
            _json_url(permalink),
            headers={"User-Agent": _ua(), "Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        listing = resp.json()
    except Exception as e:
        print(f"[thread_context] fetch failed for {permalink}: {e}")
        return None

    try:
        post = listing[0]["data"]["children"][0]["data"]
        comment_children = listing[1]["data"]["children"] if len(listing) > 1 else []
    except (KeyError, IndexError, TypeError) as e:
        print(f"[thread_context] unexpected shape for {permalink}: {e}")
        return None

    parts = [
        f"POST by u/{post.get('author')} ({post.get('score', 0)} pts, "
        f"{post.get('num_comments', 0)} comments): {post.get('title', '')}"
    ]
    selftext = (post.get("selftext") or "")[:_BODY_TRUNC]
    if selftext:
        parts.append(selftext)

    comments: list[dict] = []
    _walk(comment_children, comments)

    target_id = post_id[3:] if post_id.startswith("t1_") else None
    _mark = "[TARGET COMMENT - reply to this one] "
    lines = [
        _fmt_comment(c, _mark if target_id and c.get("id") == target_id else "")
        for c in comments[:_MAX_TOP_COMMENTS]
    ]
    # The target may sit deeper than the first N comments; append it so the
    # model always sees what it's replying to.
    if target_id and not any(_mark in ln for ln in lines):
        target = next((c for c in comments if c.get("id") == target_id), None)
        if target is not None:
            lines.append(_fmt_comment(target, _mark))

    # A comment-kind candidate whose target we never found in the fetched
    # window is undraftable — the model would be replying blind.
    if kind == "comment" and target_id and not any(_mark in ln for ln in lines):
        print(f"[thread_context] target comment {post_id} not in fetched window for {permalink}")
        return None

    if lines:
        parts.append("EXISTING COMMENTS:\n" + "\n".join(lines))
    else:
        parts.append("EXISTING COMMENTS: none yet")
    return "\n\n".join(parts)
