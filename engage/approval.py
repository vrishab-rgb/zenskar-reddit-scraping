"""Telegram approval handler + poster driver. Runs on the local machine on a
schedule (e.g. Windows Task Scheduler every ~20 min).

Each tick:
1. drain Telegram updates (button taps + edit-replies) and apply them to draft
   rows: Approve -> 'approved' (optionally with edited_text), Skip -> 'skipped'
   (+ reddit_engaged so it stops resurfacing).
2. post the approved drafts that are due, respecting the pacing knobs, via the
   old.reddit Playwright poster.

State that must survive restarts lives in Supabase (draft rows). The only local
state is the Telegram getUpdates offset, kept in a small file.
"""

import os
import random
from datetime import datetime, timezone

import db
from config import (
    MAX_DRAFT_AGE_HOURS,
    POSTER_ACTIVE_HOURS,
    POSTER_DAILY_CAP,
    POSTER_SKIP_PROBABILITY,
)
from engage import telegram
from engage.select import thread_id

_OFFSET_FILE = os.environ.get(
    "TELEGRAM_OFFSET_FILE",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".telegram_offset"),
)


def _read_offset() -> int | None:
    try:
        with open(_OFFSET_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _write_offset(update_id: int) -> None:
    with open(_OFFSET_FILE, "w") as f:
        f.write(str(update_id))


# ----- step 1: apply Telegram taps to draft state ---------------------------

def _handle_callback(cb: dict) -> None:
    """A button tap. callback_data is 'ap:<post_id>' or 'sk:<post_id>'."""
    data = cb.get("data") or ""
    cb_id = cb["id"]
    msg = cb.get("message") or {}
    message_id = msg.get("message_id")

    if data.startswith(telegram.CB_APPROVE):
        post_id = data[len(telegram.CB_APPROVE):]
        draft = db.get_draft(post_id)
        if draft and draft["status"] == "pending":
            db.update_draft(post_id, {"status": "approved"})
            telegram.answer_callback(cb_id, "Approved — will post shortly")
            if message_id:
                telegram.edit_message(message_id, f"✅ APPROVED\n{draft['permalink']}\n\n{_draft_text(draft)}")
        else:
            telegram.answer_callback(cb_id, "Already handled")
    elif data.startswith(telegram.CB_SKIP):
        post_id = data[len(telegram.CB_SKIP):]
        draft = db.get_draft(post_id)
        if draft and draft["status"] == "pending":
            db.update_draft(post_id, {"status": "skipped"})
            db.mark_engaged(post_id, thread_id(post_id, draft["permalink"]), note="skipped via telegram")
            telegram.answer_callback(cb_id, "Skipped")
            if message_id:
                telegram.edit_message(message_id, f"❌ SKIPPED\n{draft['permalink']}")
        else:
            telegram.answer_callback(cb_id, "Already handled")


def _handle_message(message: dict) -> None:
    """A plain message. If it's a reply to a draft message, treat the text as
    an edited version to post instead of the original draft."""
    reply_to = message.get("reply_to_message")
    text = (message.get("text") or "").strip()
    if not reply_to or not text:
        return
    draft = db.get_draft_by_telegram_message(reply_to.get("message_id"))
    if not draft or draft["status"] not in ("pending", "approved"):
        return
    db.update_draft(draft["post_id"], {"status": "approved", "edited_text": text})
    telegram.send_text(f"✏️ Using your edited text for r/{draft.get('subreddit')}, will post shortly.")


def drain_updates() -> int:
    """Apply all pending Telegram updates. Returns count handled."""
    offset = _read_offset()
    updates = telegram.get_updates(offset)
    handled = 0
    last_id = None
    for u in updates:
        last_id = u["update_id"]
        try:
            if "callback_query" in u:
                _handle_callback(u["callback_query"])
            elif "message" in u:
                _handle_message(u["message"])
            handled += 1
        except Exception as e:
            print(f"[approval] error handling update {u['update_id']}: {e}")
    if last_id is not None:
        _write_offset(last_id + 1)  # ack: getUpdates won't return <= this again
    return handled


# ----- step 2: post approved drafts -----------------------------------------

def _draft_text(draft: dict) -> str:
    return draft.get("edited_text") or draft["draft_text"]


def _within_active_hours() -> bool:
    lo, hi = POSTER_ACTIVE_HOURS
    return lo <= datetime.now().hour < hi


def _age_hours(draft: dict) -> float:
    created = datetime.fromisoformat(draft["created_at"].replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - created).total_seconds() / 3600


def post_due_drafts() -> None:
    """Post at most one approved draft per tick — one comment at a time keeps
    the cadence human and bounds the blast radius if something is wrong."""
    if not _within_active_hours():
        print("[approval] outside active hours, not posting")
        return
    if db.count_posted_last_24h() >= POSTER_DAILY_CAP:
        print("[approval] daily cap reached")
        return
    if random.random() < POSTER_SKIP_PROBABILITY:
        print("[approval] random skip tick (cadence jitter)")
        return

    approved = db.get_drafts_by_status("approved")
    if not approved:
        return

    draft = approved[0]
    post_id = draft["post_id"]

    # Park drafts whose thread has gone cold rather than necro-posting them.
    if _age_hours(draft) > MAX_DRAFT_AGE_HOURS:
        db.update_draft(post_id, {"status": "needs_check", "note": "stale (thread likely cold)"})
        telegram.send_text(f"⏰ Draft for r/{draft.get('subreddit')} went stale, parked. {draft['permalink']}")
        return

    from engage.poster import post_comment

    # Claim BEFORE posting: a crash leaves it in 'posting', never auto-retried.
    db.update_draft(post_id, {"status": "posting"})
    result = post_comment(draft["permalink"], draft["kind"], post_id, _draft_text(draft))

    if result.status == "posted":
        db.update_draft(post_id, {
            "status": "posted",
            "comment_url": result.comment_url,
            "posted_at": datetime.now(timezone.utc).isoformat(),
        })
        db.mark_engaged(post_id, thread_id(post_id, draft["permalink"]),
                        comment_url=result.comment_url, note="posted via poster")
        telegram.send_text(f"📤 Posted to r/{draft.get('subreddit')}\n{result.comment_url}")
    elif result.status == "logged_out":
        # Don't burn the draft; revert to approved and alert so a re-login fixes it.
        db.update_draft(post_id, {"status": "approved"})
        telegram.send_text("🔒 Poster session is logged out. Run seed_login.py to fix; draft re-queued.")
    else:
        db.update_draft(post_id, {"status": result.status, "note": result.detail})
        telegram.send_text(
            f"⚠️ Post {result.status} for r/{draft.get('subreddit')}: {result.detail}\n{draft['permalink']}"
        )


def tick() -> None:
    handled = drain_updates()
    if handled:
        print(f"[approval] handled {handled} telegram update(s)")
    post_due_drafts()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    tick()
