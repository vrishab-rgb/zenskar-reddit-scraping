# Zenskar Reddit Scraping — Design Spec

*Created 2026-04-24. Accompanies `../plans/2026-04-24-reddit-scraping-plan.md`.*

## Why this exists

Zenskar's marketing team needs real-time, targeted signal from Reddit:
1. Competitor mentions (Zuora, Chargebee, Maxio, Stripe Billing, etc.)
2. Lead/intent discovery (people shopping for billing or rev-rec tooling)
3. ICP discussion tracking (CFO / Controller / FinOps pain points)
4. On-demand historical backfill

Existing SaaS (reddit.trxnd.io) is priced poorly for our scale. Reddit's
commercial API tier ($12K+/yr) is cost-prohibitive, and the free tier's terms
likely preclude Zenskar's commercial use case. Therefore: a self-hosted tool
that does **not** touch the Reddit API.

## Core design decision: a two-layer fetch

| Layer | Source | Purpose | Volume per run | Latency |
|---|---|---|---|---|
| 1. Discovery | Reddit search RSS + subreddit `/new.rss` | Catch candidate posts | ~60 RSS fetches | ~minutes |
| 2. Enrichment | YARS (`.json` scraper) | Full body, comment tree, user profile hints | ~5–15 calls (rate-limited) | seconds each |

Discovery is cheap and broad. Enrichment is rich but rate-limited — applied
only to posts that pass a cheap Groq relevance prefilter. This keeps us far
below Reddit's unauthenticated rate ceiling (~10 req/min) and avoids IP bans.

## Separation of concerns — "pluggable fetch, stable spine"

`sources/` is the one module that can change if a data provider breaks. If
Reddit blocks RSS, YARS gets banned, or PullPush goes offline, we swap one
file without touching classification, storage, or output. This is the single
most load-bearing architectural invariant in the project — protect it.

## Rate limiting

YARS calls are gated by a process-global token bucket enforcing 1 req per
6 seconds (`YARS_MIN_INTERVAL_SECONDS` in `config.py`). A 30-minute cron run
that enriches ~15 posts takes ~90 seconds of YARS time — well inside budget.
If YARS fails on a given post (Cloudflare, 429, transient network), the
enrichment layer returns `EnrichedHit(enrichment_failed=True)` and the
pipeline falls back to RSS-only classification for that post.

## User-profile ICP hints (the edge over RSS-only tools)

For each post that passes stage-1 relevance, YARS fetches the author's recent
activity. From that we derive:
- `recent_subreddits` — top 5 by frequency
- `is_icp_likely` — intersection with `ICP_SUBS` (r/accounting, r/CFO, r/FPandA, ...)
- `prior_competitor_mentions` — scan of recent titles/bodies for `COMPETITORS`
- `account_age_days`, `total_karma` — from `/user/<u>/about.json`

These fields are cached 30 days in `reddit_user_hints` (keyed by username) so
repeat hits from the same author don't re-query YARS. That cache is what makes
this pipeline cheaper than a naive port of trxnd.io while producing better
signal on lead intent.

## Classification

Two Groq calls per post, both on `openai/gpt-oss-120b`:

1. **Relevance (stage 1)** — `"YES"` / `"NO"`. Drops ~70–90% of subreddit-RSS
   noise before we spend compute on stage 2.
2. **Bucket (stage 2)** — JSON-mode output into `{bucket, mentioned_competitors,
   buyer_persona_hint, company_size_hint, pain_points, sentiment}`.

Prompts live in `classify/prompts.py` and carry a `PROMPT_VERSION` constant;
all classifications are written with that version so historical re-classification
stays sound after prompt changes.

## Storage

Four tables in the existing Zenskar Supabase project:
- `reddit_hits` — every fetched post, keyed by Reddit fullname (`t3_xxx`)
- `reddit_classifications` — one row per post, joined by `post_id`
- `reddit_alerted` — alert dedupe (bucket + Slack channel)
- `reddit_user_hints` — 30-day TTL cache of per-author ICP signal

See `supabase_schema.sql` at the project root.

## Output routing

Each bucket has its own Slack webhook:
- `competitor_mention` → `#reddit-competitor-watch`
- `lead_signal` → `#reddit-leads`
- `icp_discussion` → `#reddit-market-insights`
- Weekly digest → `#reddit-digest`
- Monitor health → `#reddit-health` (optional)

A generic `SLACK_WEBHOOK_DEFAULT` catches any bucket without its own webhook.

## Cost — v1 is $0/month

Every line item runs on a free tier (Reddit RSS, YARS, Groq 14.4K/day,
Supabase free tier, Slack webhooks, GitHub Actions on a public repo).
Paid enhancements (Serper recall sweep ~$15/mo, residential proxies ~$10/mo,
HubSpot integration) are merit-gated — only pursued after v1 demonstrates
lead replies booked, competitor intel acted on, or ICP insights referenced.

## ToS posture

- **Reddit RSS** is a public protocol and Reddit's own canonical feed surface;
  we rate-limit and identify ourselves via User-Agent.
- **YARS** uses the `.json` suffix on public Reddit URLs — a long-documented
  developer surface. We stay well below historical unauthenticated ceilings.
- **PullPush** is a community archive; used only for on-demand backfill, not
  production monitoring.

We do not bypass login walls, do not scrape private or quarantined content,
and set an identifiable UA (`REDDIT_RSS_USER_AGENT`) on every request.

## What this tool is NOT

- Not a web dashboard (Slack + markdown is the UI)
- Not cross-platform (Reddit only; HN/Twitter come later if v1 proves out)
- Not sub-5-minute real-time (30–60 min is sufficient)
- Not a reusable generic Reddit scraper (purpose-built for Zenskar marketing)
- Not doing outreach or replies (intel only)
