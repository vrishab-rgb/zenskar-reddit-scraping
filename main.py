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
    COMPETITOR_VARIANTS,
    ICP_PAIN_PHRASES,
    INTENT_PHRASES,
    MAX_HN_QUERIES_PER_RUN,
    MAX_REDDIT_COMMENT_FEEDS_PER_RUN,
    MAX_SERPER_QUERIES_PER_RUN,
    MAX_SO_QUERIES_PER_RUN,
    MAX_STAGE1_CALLS_PER_RUN,
    MAX_STAGE2_CALLS_PER_RUN,
    MAX_STAGE3_CALLS_PER_RUN,
    SOURCE_PRIORITY,
    TARGET_SUBREDDITS,
)
from models import EnrichedHit
from outputs import slack
from sources import google_reddit, hacker_news, reddit_comments_rss, rss, stackoverflow


def _hn_queries() -> list[str]:
    """HN queries are intentionally narrow. Algolia returns ANY HN
    content matching the term in the last 72h — generic phrases like
    'usage-based billing' surface dozens of unrelated tangents. Keep the
    list to high-precision terms that almost always indicate buyer-relevant
    discussion: competitor names, and the most concrete intent signals."""
    high_precision_intent = [
        "usage-based billing",
        "metered billing",
        "subscription billing platform",
        "revenue recognition software",
        "billing automation platform",
    ]
    return COMPETITOR_SEARCH_TERMS + high_precision_intent


def _serper_queries() -> list[str]:
    """Serper sees the entire indexed Reddit. Throw the kitchen sink at it —
    competitor variants, pain phrases, intent phrases. Each query is a paid
    API call so MAX_SERPER_QUERIES_PER_RUN is the actual cost knob."""
    queries = list(COMPETITOR_SEARCH_TERMS)
    queries.extend(COMPETITOR_VARIANTS)
    queries.extend(INTENT_PHRASES)
    queries.extend(ICP_PAIN_PHRASES)
    seen = set()
    deduped = []
    for q in queries:
        ql = q.lower()
        if ql in seen:
            continue
        seen.add(ql)
        deduped.append(q)
    return deduped


def _comments_rss_keywords() -> list[str]:
    """Comment-RSS post-filtering is client-side, so we keep the keyword
    list small and high-precision. Competitor canonical names + tightest
    intent phrases — anything noisier just bloats the per-feed match."""
    return COMPETITOR_SEARCH_TERMS + INTENT_PHRASES


def _discover() -> list:
    """Pull from every source, merge by post_id, sort by source priority so
    higher-signal candidates get the LLM budget first."""
    by_id: dict[str, object] = {}
    counts: dict[str, int] = {}

    def _ingest(source_label: str, hits: list) -> None:
        counts[source_label] = len(hits)
        for h in hits:
            existing = by_id.get(h.post_id)
            if existing is None:
                by_id[h.post_id] = h
            else:
                # Same post seen from another source: union matched_keywords,
                # promote source if the new one has higher priority.
                for k in h.matched_keywords:
                    if k not in existing.matched_keywords:
                        existing.matched_keywords.append(k)
                if SOURCE_PRIORITY.get(h.source, 0) > SOURCE_PRIORITY.get(existing.source, 0):
                    existing.source = h.source

    print(f"[main] discovery: subs={len(TARGET_SUBREDDITS)} "
          f"reddit_search_terms={len(COMPETITOR_SEARCH_TERMS) + len(INTENT_PHRASES)}")
    _ingest("reddit_rss", rss.fetch_all(
        TARGET_SUBREDDITS, COMPETITOR_SEARCH_TERMS + INTENT_PHRASES,
    ))

    _ingest("reddit_comments", reddit_comments_rss.fetch_all(
        TARGET_SUBREDDITS, _comments_rss_keywords(), MAX_REDDIT_COMMENT_FEEDS_PER_RUN,
    ))

    _ingest("hacker_news", hacker_news.fetch_all(
        _hn_queries(), MAX_HN_QUERIES_PER_RUN,
    ))

    _ingest("stackoverflow", stackoverflow.fetch_all(MAX_SO_QUERIES_PER_RUN))

    _ingest("google_reddit", google_reddit.fetch_all(
        _serper_queries(), MAX_SERPER_QUERIES_PER_RUN,
    ))

    candidates = list(by_id.values())
    # Sort by source priority desc — when stage-1 budget bites, we burn it
    # on the highest-signal candidates first.
    candidates.sort(key=lambda h: SOURCE_PRIORITY.get(h.source, 0), reverse=True)

    src_breakdown = "  ".join(f"{k}={v}" for k, v in counts.items())
    print(f"[main] discovered {len(candidates)} unique candidates  ({src_breakdown})")
    return candidates


def _process_one(hit, counters: Counter, dry_run: bool) -> None:
    if db.is_seen(hit.post_id):
        counters["already_seen"] += 1
        return

    # Track per-source candidate flow even when stage-1 is skipped.
    counters[f"src_{hit.source}_seen"] += 1

    # Skip entirely if stage-1 budget is exhausted — and critically, do NOT
    # insert into reddit_hits, so this post is reconsidered on the next run.
    if counters["stage1_called"] >= MAX_STAGE1_CALLS_PER_RUN:
        counters["stage1_budget_skipped"] += 1
        return
    counters["stage1_called"] += 1

    try:
        passed = relevance.is_relevant(hit.title, hit.body)
    except RelevanceRateLimited:
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
        print(f"[main][dry-run] would classify: {hit.post_id} ({hit.source}) — {hit.title[:80]}")
        return

    # Multi-source means we no longer have an enrichment step — title+body
    # (plus search-snippet body for google_reddit) is what stage-2 sees.
    enriched = EnrichedHit(hit=hit, enrichment_failed=False)

    # Stage-2 budget — protects the 120B daily token bucket.
    if counters["stage2_called"] >= MAX_STAGE2_CALLS_PER_RUN:
        counters["stage2_budget_skipped"] += 1
        return
    counters["stage2_called"] += 1

    try:
        cls = bucket_mod.classify(enriched)
    except BucketRateLimited:
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
    # if the 8B quota is exhausted, we still post the alert without a draft.
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
        counters[f"src_{hit.source}_alerted"] += 1


def _summary(counters: Counter) -> str:
    keys = [
        "new_inserted", "already_seen",
        "stage1_called", "stage1_passed", "stage1_dropped",
        "stage1_rate_limited", "stage1_budget_skipped",
        "stage2_called", "stage2_rate_limited", "stage2_budget_skipped",
        "bucket_competitor_mention", "bucket_lead_signal", "bucket_icp_discussion", "bucket_noise",
        "stage3_called", "stage3_skipped_by_model", "stage3_rate_limited", "stage3_budget_skipped",
        "stage3_strategy_direct_recommend", "stage3_strategy_soft_mention",
        "stage3_strategy_none", "stage3_strategy_skip",
        "alerts_posted", "already_alerted",
    ]
    pairs = [f"{k}={counters.get(k, 0)}" for k in keys]
    # Per-source visibility separately so the line stays readable.
    src_keys = sorted(k for k in counters if k.startswith("src_"))
    src_pairs = [f"{k}={counters[k]}" for k in src_keys]
    return "  ".join(pairs) + (("  ||  " + "  ".join(src_pairs)) if src_pairs else "")


def run(dry_run: bool = False) -> None:
    counters: Counter = Counter()
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
