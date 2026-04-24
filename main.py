import argparse
import sys
from collections import Counter

import db
from classify import bucket as bucket_mod
from classify import relevance
from config import (
    COMPETITOR_SEARCH_TERMS,
    INTENT_PHRASES,
    MAX_ENRICHMENTS_PER_RUN,
    MAX_STAGE1_CALLS_PER_RUN,
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

    if not dry_run:
        db.upsert_hit(hit)
    counters["new_inserted"] += 1

    if not relevance.is_relevant(hit.title, hit.body):
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

    cls = bucket_mod.classify(enriched)
    db.record_classification(cls)
    counters[f"bucket_{cls.bucket}"] += 1

    if cls.bucket == "noise":
        return
    if db.was_alerted(hit.post_id):
        counters["already_alerted"] += 1
        return

    channel = slack.post_alert(enriched, cls)
    if channel:
        db.mark_alerted(hit.post_id, cls.bucket, channel)
        counters["alerts_posted"] += 1


def _summary(counters: Counter) -> str:
    keys = [
        "new_inserted", "already_seen", "stage1_called", "stage1_passed", "stage1_dropped",
        "stage1_budget_skipped", "enrich_called", "enrich_budget_skipped",
        "yars_ok", "yars_failed",
        "bucket_competitor_mention", "bucket_lead_signal", "bucket_icp_discussion", "bucket_noise",
        "alerts_posted", "already_alerted",
    ]
    pairs = [f"{k}={counters.get(k, 0)}" for k in keys]
    return "  ".join(pairs)


def run(dry_run: bool = False) -> None:
    counters: Counter = Counter()
    candidates = _discover()
    for hit in candidates:
        try:
            _process_one(hit, counters, dry_run)
        except Exception as e:
            counters["errors"] += 1
            print(f"[main] error processing {hit.post_id}: {e}")
    summary = _summary(counters)
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
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    run(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
