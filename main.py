import argparse
import sys
from collections import Counter

import db
from classify import bucket as bucket_mod
from classify import comment_suggest as suggest_mod
from classify import groq_quota
from classify import relevance
from classify.bucket import BucketRateLimited
from classify.comment_suggest import CommentSuggestRateLimited
from classify.relevance import RelevanceRateLimited
from config import (
    COMPETITOR_SEARCH_TERMS,
    INTENT_PHRASES,
    MAX_ENRICHMENTS_PER_RUN,
    MAX_STAGE1_CALLS_PER_RUN,
    MAX_STAGE3_CALLS_PER_RUN,
    TARGET_SUBREDDITS,
)
from models import EnrichedHit
from outputs import slack
from sources import rss, yars_enrich


def _discover() -> list:
    print(f"[main] Layer 1 discovery: {len(TARGET_SUBREDDITS)} subs, "
          f"{len(COMPETITOR_SEARCH_TERMS) + len(INTENT_PHRASES)} search terms")
    keywords = COMPETITOR_SEARCH_TERMS + INTENT_PHRASES
    hits = rss.fetch_all(TARGET_SUBREDDITS, keywords)
    print(f"[main] discovered {len(hits)} unique candidates from RSS")
    return hits


def _process_one(hit, counters: Counter, dry_run: bool) -> None:
    if db.is_seen(hit.post_id):
        counters["already_seen"] += 1
        return

    # Skip entirely if stage-1 budget is exhausted — and critically, do NOT
    # insert into reddit_hits, so this post is reconsidered on the next run.
    if counters["stage1_called"] >= MAX_STAGE1_CALLS_PER_RUN:
        counters["stage1_budget_skipped"] += 1
        return
    counters["stage1_called"] += 1

    try:
        passed = relevance.is_relevant(hit.title, hit.body)
    except RelevanceRateLimited:
        # Groq quota exhausted. Do NOT upsert — let this run's counter mark
        # the event and the next run (or next UTC day) will retry.
        counters["stage1_rate_limited"] += 1
        return

    if not dry_run:
        db.upsert_hit(hit)
    counters["new_inserted"] += 1

    if not passed:
        counters["stage1_dropped"] += 1
        return
    counters["stage1_passed"] += 1

    if dry_run:
        print(f"[main][dry-run] would enrich + classify: {hit.post_id} — {hit.title[:80]}")
        return

    # Enrichment budget: if exhausted, classify on RSS-only context.
    if counters["enrich_called"] >= MAX_ENRICHMENTS_PER_RUN:
        enriched = EnrichedHit(hit=hit, enrichment_failed=True)
        counters["enrich_budget_skipped"] += 1
    else:
        counters["enrich_called"] += 1
        enriched = yars_enrich.enrich(hit)
        if enriched.enrichment_failed:
            counters["yars_failed"] += 1
        else:
            counters["yars_ok"] += 1

    try:
        cls = bucket_mod.classify(enriched)
    except BucketRateLimited:
        # Stage-2 quota exhausted. We already upserted the hit above, but
        # skip recording a classification so the next run (post quota reset)
        # re-runs stage-2 and fills it in.
        counters["stage2_rate_limited"] += 1
        return

    db.record_classification(cls)
    counters[f"bucket_{cls.bucket}"] += 1

    if cls.bucket == "noise":
        return
    if db.was_alerted(hit.post_id):
        counters["already_alerted"] += 1
        return

    # Stage-3: draft a suggested reply for the marketing team. Best-effort —
    # if the 8B quota is exhausted, we still post the alert without a draft
    # rather than dropping the alert entirely.
    suggestion = None
    if counters["stage3_called"] >= MAX_STAGE3_CALLS_PER_RUN:
        counters["stage3_budget_skipped"] += 1
    else:
        counters["stage3_called"] += 1
        try:
            suggestion = suggest_mod.suggest(enriched, cls)
        except CommentSuggestRateLimited:
            counters["stage3_rate_limited"] += 1
            suggestion = None
        if suggestion is not None:
            db.record_comment_suggestion(suggestion)
            if suggestion.suggested_comment:
                counters[f"stage3_strategy_{suggestion.plug_strategy}"] += 1
            else:
                counters["stage3_skipped_by_model"] += 1

    channel = slack.post_alert(enriched, cls, suggestion)
    if channel:
        db.mark_alerted(hit.post_id, cls.bucket, channel)
        counters["alerts_posted"] += 1


def _summary(counters: Counter) -> str:
    keys = [
        "new_inserted", "already_seen", "stage1_called", "stage1_passed", "stage1_dropped",
        "stage1_rate_limited", "stage1_budget_skipped",
        "enrich_called", "enrich_budget_skipped", "yars_ok", "yars_failed",
        "stage2_rate_limited",
        "bucket_competitor_mention", "bucket_lead_signal", "bucket_icp_discussion", "bucket_noise",
        "stage3_called", "stage3_skipped_by_model", "stage3_rate_limited", "stage3_budget_skipped",
        "stage3_strategy_direct_recommend", "stage3_strategy_soft_mention",
        "stage3_strategy_none", "stage3_strategy_skip",
        "alerts_posted", "already_alerted",
    ]
    pairs = [f"{k}={counters.get(k, 0)}" for k in keys]
    return "  ".join(pairs)


def run(dry_run: bool = False) -> None:
    counters: Counter = Counter()
    # Seed daily-usage baseline from Supabase so format_summary can show
    # accurate "tokens left today" — Groq doesn't expose this in headers.
    groq_quota.seed_baseline_from_db()
    candidates = _discover()
    for hit in candidates:
        try:
            _process_one(hit, counters, dry_run)
        except Exception as e:
            counters["errors"] += 1
            print(f"[main] error processing {hit.post_id}: {e}")
    if not dry_run:
        groq_quota.flush_usage_to_db()
    quota = groq_quota.format_summary()
    summary = f"{_summary(counters)}  |  {quota}"
    print(f"[main] {summary}")

    # Warn loudly if YARS failure rate is high this run
    attempts = counters["yars_ok"] + counters["yars_failed"]
    if attempts >= 5 and counters["yars_failed"] / attempts > 0.5:
        slack.post_health(f"⚠️ YARS failure rate > 50% this run: {summary}")
    else:
        slack.post_health(summary)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Discover + filter but don't write or alert")
    ap.add_argument("--probe-quota", action="store_true",
                    help="Skip the run; just probe Groq quota for both models we use and print headroom")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    if args.probe_quota:
        groq_quota.seed_baseline_from_db()
        groq_quota._probe("llama-3.1-8b-instant")
        groq_quota._probe("openai/gpt-oss-120b")
        groq_quota.flush_usage_to_db()
        print(groq_quota.format_summary())
        return 0
    run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
