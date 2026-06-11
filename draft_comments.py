"""Drafting entrypoint — runs in the daily monitor workflow after the pipeline
has discovered/classified the day's hits. Selects the best fresh candidates,
fetches live thread context, drafts a comment for each, runs the quality gate,
and sends survivors to Telegram for thumbs-up/down approval.

Posting is NOT done here. The local approval poller (engage/approval.py) posts
approved drafts. This stage only produces and queues drafts.
"""

import sys

import db
from config import DRAFT_LOOKBACK_HOURS, MAX_DRAFTS_PER_RUN
from engage import drafter, telegram
from engage.prompts import DRAFT_PROMPT_VERSION
from engage.select import pick, thread_id
from engage.thread_context import fetch_digest


def _record_rejected(post_id: str, permalink: str, reason: str) -> None:
    """A deliberate non-draft (model skipped or gate failed). Recorded so the
    candidate isn't re-drafted next run, but NOT marked engaged — a human could
    still comment manually."""
    db.insert_draft({
        "post_id": post_id,
        "permalink": permalink,
        "draft_text": "",
        "status": "rejected",
        "note": reason,
        "prompt_version": DRAFT_PROMPT_VERSION,
    })


def run() -> None:
    engaged_ids, engaged_threads = db.get_engaged()
    drafted_ids = db.get_drafted_ids()  # raises on failure -> abort (fail closed)
    rows = db.get_recent_classified(DRAFT_LOOKBACK_HOURS)

    candidates = pick(rows, engaged_ids, engaged_threads, drafted_ids, MAX_DRAFTS_PER_RUN)
    print(f"[draft] {len(rows)} classified rows -> {len(candidates)} candidates to draft")

    sent = 0
    for c in candidates:
        post_id = c["post_id"]
        digest = fetch_digest(c["permalink"], c["kind"], post_id)
        if digest is None:
            # Transient fetch failure or undraftable (target comment gone).
            # Leave it undrafted so it's retried next run; don't poison it.
            print(f"[draft] no thread context for {post_id}, skipping this run")
            continue

        d = drafter.draft(c, digest)
        if d is None:
            print(f"[draft] drafter API/parse error for {post_id}, retry next run")
            continue

        if d.skip or not d.comment:
            _record_rejected(post_id, c["permalink"], f"model skip: {d.skip_reason or 'no comment'}")
            print(f"[draft] {post_id} skipped by model: {d.skip_reason}")
            continue

        gate = drafter.quality_gate(d.comment)
        if gate:
            _record_rejected(post_id, c["permalink"], f"gate: {gate}")
            print(f"[draft] {post_id} failed gate: {gate}")
            continue

        message_id = telegram.send_draft(c, d.comment)
        db.insert_draft({
            "post_id": post_id,
            "permalink": c["permalink"],
            "subreddit": c.get("subreddit"),
            "kind": c["kind"],
            "title": c.get("title"),
            "draft_text": d.comment,
            "status": "pending",
            "model": drafter.model_name(),
            "prompt_version": DRAFT_PROMPT_VERSION,
            "telegram_message_id": message_id,
        })
        sent += 1
        print(f"[draft] queued {post_id} -> telegram msg {message_id} (mention={d.mention})")

    print(f"[draft] done: {sent} draft(s) sent to telegram")


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
