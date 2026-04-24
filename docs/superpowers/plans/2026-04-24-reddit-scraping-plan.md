# Zenskar Reddit Scraping — Self-Hosted Replacement for reddit.trxnd.io

## Context

Zenskar's marketing team currently pays (or is considering paying) for reddit.trxnd.io to monitor Reddit for competitor mentions, ICP discussions, and lead-gen signals. The SaaS pricing is unattractive for our scale, and — critically — Reddit's commercial API tier ($12K+/year) is also out of reach, and Zenskar's commercial use case likely precludes using the free tier even indirectly (as the existing `Zenskar Reviews Scraper` does via PRAW).

We'll build a standalone Python monitoring tool that mirrors the spine of `D:\Projects\Zenskar Reviews Scraper` (Python 3.11 + Supabase dedupe + Groq classification + Slack alerts + GitHub Actions cron) but replaces the fetch layer with **no-Reddit-API alternatives**: Reddit RSS for discovery, YARS (MIT-licensed `.json` scraper from github.com/datavorous/yars) for enrichment, and PullPush for historical backfill. **Total projected cost for v1: $0/month** — everything runs on free tiers. Paid enhancements (Serper for recall, residential proxies for scale) are explicitly deferred to v2, contingent on v1 proving marketing merit.

The tool covers four jobs selected by Vrishab:
1. Competitor mention alerts (Zuora, Maxio, Chargebee, Stripe Billing, Recurly, Ordway, Metronome, Tabs, BillingPlatform, Sage Intacct, ZoneBilling, Zenskar)
2. Lead / intent discovery (people asking for billing / rev-rec / usage-pricing help)
3. ICP discussion tracking (CFO/Controller/FinOps pain-point qualitative signal)
4. One-off historical backfill (ad-hoc keyword archives for analysis)

Output: real-time Slack alerts **and** weekly markdown digest.

---

## Goals

- **v1 is $0/month — fully free tier across every component.** Prove marketing value before paying for anything.
- Monitor ~20 subreddits + ~40 keywords continuously, posting new relevant hits to Slack within **15–60 minutes** of the Reddit post going live (bounded by a 30-minute cron)
- Primary data source is **Reddit's own search RSS** (few-minute freshness via Reddit's internal index) — no paid search API in v1
- Classify each hit into one of four buckets (competitor mention / lead signal / ICP discussion / noise) using Groq free-tier LLM
- Produce a weekly Monday-morning markdown digest summarising the week's themes, top threads, and lead opportunities
- Support on-demand historical backfill for a given (keyword, date range) tuple via PullPush (free community archive)
- Stay fully off the Reddit official API (no PRAW, no OAuth, no `api.reddit.com` endpoints)

## Non-Goals

- No web dashboard UI (Slack + markdown reports is the interface)
- No cross-platform monitoring — only Reddit (Twitter/LinkedIn/HN can come later)
- No sub-5-minute freshness; 30–60 minutes is sufficient
- Not a generic Reddit scraping library for reuse elsewhere — purpose-built for Zenskar
- No replies, DMs, or outreach automation from this tool

---

## Data-Access Strategy (The Core Design Decision)

**v1 uses only free sources** via a two-layer fetch pattern: cheap RSS for discovery, richer YARS (`.json` scraping) for enrichment on high-signal candidates only.

| Source | Use in v1 | Freshness | Volume / run | Cost |
|---|---|---|---|---|
| **Reddit search RSS** (`search.rss?q=<term>&sort=new&t=day`) | **Discovery** of keyword mentions across all of Reddit | Few minutes (Reddit's own index) | ~40 calls | Free |
| **Reddit subreddit RSS** (`/r/<sub>/new.rss`) | **Discovery** inside target subs (ICP net, catches posts even without keyword match) | ~5–15 min | ~20 calls | Free |
| **YARS** (`github.com/datavorous/yars`, uses `.json` endpoints) | **Enrichment** of high-signal candidates: full comment tree + user-profile lookup (recent subreddits posted in, karma, account age) | Real-time | ~5–15 calls | Free |
| **PullPush API** (`api.pullpush.io/reddit/submission/search/`) | Historical backfill only (via `backfill.py`, run on demand) | Stale (days) | On demand | Free |

### The two-layer pattern

**Layer 1 — Discovery (RSS, cheap):**
1. For each keyword in `COMPETITORS + INTENT_PHRASES`, fetch Reddit search RSS globally, parse new entries.
2. For each subreddit in `TARGET_SUBREDDITS`, fetch `/new.rss`, parse new entries.
3. Merge by `post_id`, dedupe against Supabase. Run cheap Groq stage-1 relevance filter on title + RSS summary.

**Layer 2 — Enrichment (YARS, rate-limited):**
Only for posts that pass stage-1 relevance:
4. YARS `scrape_post_details(permalink)` → full post body + top-level comments.
5. YARS `scrape_user_data(author)` → recent submissions + comments. From that, derive:
   - Does this user post in finance/accounting subreddits? (ICP persona signal)
   - Account age and karma (spam filter)
   - Prior mentions of competitor products by this user
6. Pass enriched context to Groq stage-2 bucket classification. Persist into `reddit_classifications` + new `reddit_user_hints` table.

Rate-limit YARS calls to **1 request per 6 seconds** (10 req/min, Reddit's unauthenticated `.json` ceiling). Expected volume is ~10 enrichment passes per 30-min cron × 2–3 YARS calls each = ~25 calls max, 150 seconds of YARS time per run. Well within budget.

Graceful degradation: if a YARS call fails (Cloudflare challenge, 429, transient error), fall back to RSS-only classification for that post and continue. Log failure for later retry.

### Why this pattern is better than either alone

| | RSS only | YARS only | RSS + YARS (chosen) |
|---|---|---|---|
| Discovery latency | **Minutes** | Minutes | **Minutes** |
| Full comment trees | No | Yes | **Yes (for enriched)** |
| User-profile ICP hints | No | Yes | **Yes (for enriched)** |
| Rate-limit risk | Low | **High** | **Low** |
| Volume-tolerant | Yes | **No** | **Yes** |

### Why YARS over rolling our own `.json` scraper

YARS already handles: URL normalisation, JSON→dict mapping for Reddit's quirky schema, comment-tree flattening, image URL extraction, pagination through user activity. MIT-licensed, 185 stars, active. Installing via `pip install git+https://github.com/datavorous/yars.git` — if it becomes a bottleneck, vendoring the source into `sources/_yars_vendor/` is a one-commit fix. Either way, YARS saves us ~300 lines of boilerplate.

### Expected end-to-end latency

15–60 minutes from post creation to Slack alert, bounded by the 30-minute cron.

### v2 enhancements (spend only after v1 proves merit)

- **Serper.dev daily sweep** (~$15/mo) — recall safety net for mentions in subreddits we don't directly monitor and for older threads gaining traction.
- **Residential proxy pool** — if YARS IP bans become frequent in production, ~$10/mo for a small Bright Data / Webshare rotating proxy bucket. Deferrable: GitHub Actions runners already rotate IPs between runs, which is a form of natural rotation.
- **Hacker News secondary source** — HN's Algolia API is free and near-real-time; worth adding once Reddit proves out the pipeline.
- **Comment-level monitoring as a first-class source** — currently v1 watches submissions and pulls comments only as enrichment. If comment threads turn out to be where the signal is, add a discovery-level comment RSS feed (`/r/<sub>/comments/.rss`).

### Explicitly avoided

- PRAW / OAuth flows of any kind — commercial use concern
- Browser automation with residential proxies — overkill, costly, ToS-risky
- Pushshift-era archives (now stale)
- Any paid search/scraping API in v1

---

## Architecture

Directory layout mirrors `Zenskar Reviews Scraper`:

```
D:\Projects\Zenskar Reddit Scraping\
├── main.py                      # Orchestrator: runs one monitor pass
├── backfill.py                  # CLI: python backfill.py --keyword "Zuora" --from 2025-01-01
├── digest.py                    # Weekly rollup: reads Supabase, writes reports/YYYY-WW.md
├── config.py                    # Competitors, keywords, subreddits, intent patterns
├── models.py                    # RedditHit dataclass (post_id, subreddit, author, title, body, url, created_utc, score, num_comments)
├── db.py                        # Supabase client + schema helpers
├── sources/
│   ├── __init__.py
│   ├── rss.py                   # Layer 1 discovery: subreddit new RSS + global search RSS
│   ├── yars_enrich.py           # Layer 2 enrichment: wraps YARS for post details + user profiles (rate-limited)
│   └── pullpush.py              # Historical backfill (used by backfill.py only)
│   # serper.py intentionally omitted in v1 — defer to v2 once merit is proven
├── classify/
│   ├── __init__.py
│   ├── relevance.py             # Groq LLM: is this about billing/O2C at all? (cheap prefilter)
│   ├── bucket.py                # Groq LLM: classify into competitor/lead/ICP/noise + extract fields
│   └── prompts.py               # Prompt templates (versioned)
├── outputs/
│   ├── __init__.py
│   ├── slack.py                 # Webhook poster with per-bucket routing
│   └── digest_renderer.py       # Markdown builder for weekly digest
├── reports/                     # Generated weekly digests (gitignored except samples)
├── requirements.txt
├── .env.example
├── .env                         # gitignored
├── .gitignore
├── .github/workflows/
│   ├── monitor.yml              # Cron: every 30 min (*/30 * * * *) → python main.py
│   └── weekly-digest.yml        # Cron: Monday 09:00 UTC (0 9 * * 1) → python digest.py
├── .claude/
│   └── settings.local.json      # Mirror Reviews Scraper's permission allowlist
├── tests/
│   ├── test_sources_rss.py
│   ├── test_sources_yars_enrich.py
│   ├── test_classify_bucket.py
│   ├── test_db_dedupe.py
│   ├── test_outputs_slack.py
│   └── fixtures/
│       ├── rss_sample.xml
│       ├── yars_post_sample.json
│       └── yars_user_sample.json
└── docs/superpowers/
    ├── plans/2026-04-24-reddit-scraping-plan.md
    └── specs/2026-04-24-reddit-scraping-design.md
```

### Key modules in more detail

**`sources/rss.py`** (Layer 1 — discovery) — uses `feedparser` for two distinct endpoint families:
- **Global keyword search RSS**: `https://www.reddit.com/search.rss?q=<term>&sort=new&t=day` — one call per keyword in `COMPETITORS + INTENT_PHRASES`. This is Reddit's own internal search index, updated within minutes of new posts.
- **Per-subreddit new-post RSS**: `https://www.reddit.com/r/<sub>/new.rss` — one call per target subreddit.

Sets a descriptive User-Agent (`zenskar-marketing-monitor/1.0 (contact: priyam.s@zenskar.com)`). Exponential backoff on 429/503. Post-filters search RSS results locally against the exact keyword, because Reddit's search tokeniser returns loose matches. Returns `RedditHit` objects populated with everything RSS exposes (title, author, permalink, summary, created_utc) — no body fetch here; that's Layer 2's job.

**`sources/yars_enrich.py`** (Layer 2 — enrichment) — thin wrapper over YARS (`from yars import YARS`), called only for posts that passed Groq stage-1 relevance. Three methods:
- `fetch_post(permalink)` → full body text + top-level comments (list of `{author, body, score}`).
- `fetch_user_hints(username)` → summarised user profile: recent subreddits posted in (top 5 by frequency), account age in days, total karma, any prior mentions of competitor brands from `COMPETITORS`.
- `enrich(hit)` → orchestrates both, returns an `EnrichedHit` wrapping the original `RedditHit` plus comment/user data.

Global token-bucket rate limiter enforces **1 request per 6 seconds** (Reddit's unauthenticated `.json` ceiling is ~10 req/min; we pace below that with headroom). All YARS failures caught and logged; caller falls back to RSS-only data. User hints are cached in `reddit_user_hints` table keyed by username with a 30-day TTL — repeat hits from the same user don't re-query YARS.

**`sources/pullpush.py`** — only used by `backfill.py`. Paginates `api.pullpush.io/reddit/submission/search/` by date range + query; also hits `/comment/search/` for comment-level hits. Free community archive.

**`classify/bucket.py`** — two-stage Groq call:
- Stage 1 (cheap): "Is this post related to billing, revenue recognition, subscription pricing, usage-based pricing, accounting software, or finance operations?" → yes/no. Drops 80%+ of false positives before paying for stage 2.
- Stage 2 (richer): "Classify into {competitor_mention, lead_signal, icp_discussion, noise}. Extract: mentioned_competitors[], buyer_persona_hint (CFO/Controller/FinOps/RevOps/other/unknown), company_size_hint (smb/midmarket/enterprise/unknown), pain_points[], sentiment (pos/neu/neg)."

Uses Groq's GPT-OSS 120B model (same as Reviews Scraper's `sentiment.py`). Structured output via JSON mode. Prompt versioned in `classify/prompts.py` so re-classification of historical hits is possible later.

**`db.py`** — Supabase client wrapping three tables (see Storage section). Reuse `SUPABASE_URL` and `SUPABASE_KEY` env pattern from Reviews Scraper.

**`outputs/slack.py`** — posts to different webhook URLs by bucket:
- `SLACK_WEBHOOK_COMPETITORS` → `#reddit-competitor-watch`
- `SLACK_WEBHOOK_LEADS` → `#reddit-leads`
- `SLACK_WEBHOOK_ICP` → `#reddit-market-insights`
- Fallback `SLACK_WEBHOOK_DEFAULT` if a bucket-specific one is missing.

Message format: emoji header by bucket, post title, subreddit + author, snippet (first 300 chars), permalink, inline field with classified persona + sentiment.

---

## Storage — Supabase Schema

Three tables in the existing Zenskar Supabase project:

```sql
create table reddit_hits (
  post_id           text primary key,              -- e.g. 't3_abc123'
  fetched_at        timestamptz not null default now(),
  created_utc       timestamptz not null,          -- Reddit's original post time
  subreddit         text not null,
  author            text,
  title             text not null,
  body              text,
  permalink         text not null,
  score             int,
  num_comments      int,
  source            text not null,                 -- 'serper' | 'rss' | 'pullpush'
  matched_keywords  text[] not null default '{}'   -- which configured keywords triggered this
);

create table reddit_classifications (
  post_id                text primary key references reddit_hits(post_id),
  bucket                 text not null,            -- 'competitor' | 'lead' | 'icp' | 'noise'
  mentioned_competitors  text[] default '{}',
  buyer_persona_hint     text,
  company_size_hint      text,
  pain_points            text[] default '{}',
  sentiment              text,
  prompt_version         text not null,            -- e.g. 'v1' so we can re-classify later
  classified_at          timestamptz not null default now()
);

create table reddit_alerted (
  post_id        text primary key references reddit_hits(post_id),
  bucket         text not null,
  slack_channel  text not null,
  alerted_at     timestamptz not null default now()
);

create table reddit_user_hints (
  username             text primary key,
  fetched_at           timestamptz not null default now(),
  recent_subreddits    text[] not null default '{}',   -- top 5 subs this user has posted in recently
  account_age_days     int,
  total_karma          int,
  prior_competitor_mentions text[] not null default '{}',  -- any COMPETITORS they've posted about before
  is_icp_likely        boolean                          -- true if recent_subreddits intersects finance/accounting subs
);
```

Dedupe logic: before processing a candidate, `select 1 from reddit_hits where post_id = ?`. Before alerting, `select 1 from reddit_alerted where post_id = ?`. Before a YARS user-fetch, `select fetched_at from reddit_user_hints where username = ?` and skip if fetched within the last 30 days.

---

## Data Flow

### Every-30-minute monitor (`main.py` via `monitor.yml`, cron `*/30 * * * *`)

**Layer 1 — discovery (RSS, fast):**
1. Load config (keywords, subreddits, competitor terms, intent patterns).
2. Fetch in parallel:
   - Reddit search RSS: for each keyword in `COMPETITORS + INTENT_PHRASES`, fetch `search.rss?q=<term>&sort=new&t=day`. Post-filter returned entries against the actual keyword (Reddit's search tokenises, so phrase matches need local verification).
   - Subreddit RSS: for each target subreddit, pull `/new.rss`.
3. Merge candidates by `post_id`. Drop anything already in `reddit_hits`.
4. Insert new candidates into `reddit_hits` with `source='rss_search'` or `'rss_sub'` and RSS-provided title + summary.
5. Run Groq stage-1 relevance filter on (title + summary). Drop irrelevant — this typically eliminates 70–90% of candidates (subreddit RSS picks up a lot of unrelated posts).

**Layer 2 — enrichment (YARS, slow but rich) — only for posts that passed stage-1:**

6. For each surviving candidate, call `yars_enrich.enrich(hit)` under a 1-req-per-6-seconds global limiter. This fetches:
   - Full post body + top-level comments
   - User profile hints (cached 30 days in `reddit_user_hints`)
7. Run Groq stage-2 bucket classification on the enriched context (body + comments + user hints). Insert into `reddit_classifications`.
8. For each non-noise classification not already in `reddit_alerted`: post to the bucket-specific Slack webhook, insert into `reddit_alerted`.

**Failure handling:**
- Any YARS call failing (429, Cloudflare, transient network) logs the error and falls back to RSS-only classification for that post. Log a counter per run so we can see if YARS failure rate creeps up over time.
- If YARS fails for >50% of enrichment attempts in a single run, emit a warning Slack alert to a maintenance channel so we know to investigate.

### Weekly digest (`digest.py` via `weekly-digest.yml`)
1. Query `reddit_hits` joined with `reddit_classifications` for `created_utc` in last 7 days.
2. Group by bucket:
   - Top competitor mentions (by score + comment count), with brief one-line summary
   - Top lead opportunities (bucket='lead' sorted by created_utc desc), with author + permalink + extracted pain points
   - Recurring themes across ICP discussions (cluster by shared pain_points array using simple cosine/Jaccard over keywords)
3. Render to `reports/YYYY-WW.md` (ISO week number).
4. Post a summary block to a dedicated `SLACK_WEBHOOK_DIGEST` channel with a link to the committed file on GitHub.
5. Commit `reports/YYYY-WW.md` back to the repo via GitHub Actions push (using `peter-evans/create-pull-request` or a simple push step).

### On-demand backfill (`backfill.py`, run locally)
```bash
python backfill.py --keyword "Chargebee alternative" --from 2023-01-01 --to 2024-12-31
```
1. Paginate PullPush for submissions matching keyword in date range.
2. Optionally paginate for comments too (`--include-comments` flag).
3. Dedupe + insert into `reddit_hits` with `source='pullpush'`.
4. Optionally classify (skip by default — backfill volumes can be large and Groq costs add up). Flag `--classify` forces it.
5. Emit a CSV summary to `reports/backfill-<keyword>-<timestamp>.csv`.

---

## Configuration (`config.py`)

```python
# Subreddits scanned every hour via RSS
TARGET_SUBREDDITS = [
    "SaaS", "startups", "Entrepreneur", "SaaStr",
    "accounting", "Accountant", "FPandA",
    "finance", "CFO", "Controller", "revenueoperations",
    "fintech", "payments",
    "sysadmin", "smallbusiness",
    "salesforce", "netsuite", "quickbooks",
]

# Competitor names — used for RSS search queries + post-fetch keyword filter
COMPETITORS = [
    "Zenskar",                     # own-brand monitoring
    "Zuora", "Maxio", "Chargify", "SaaSOptics",
    "Stripe Billing", "Chargebee", "Recurly",
    "Ordway", "Metronome", "Tabs", "BillingPlatform",
    "Sage Intacct", "ZoneBilling",
]

# Intent phrases (lead signals) — used for Reddit search RSS queries
INTENT_PHRASES = [
    "usage-based billing", "usage based pricing", "metered billing",
    "revenue recognition software", "ASC 606 software",
    "billing automation platform", "subscription billing platform",
    "alternative to Chargebee", "alternative to Zuora", "alternative to Maxio",
    "Chargebee vs", "Zuora vs", "Stripe Billing vs",
    "replacing Stripe Billing", "migrating from Zuora",
    "billing software recommendations", "rev rec tool",
]

# ICP conversation topics (broader nets; high-volume subs only)
ICP_TOPICS = [
    "close the books", "month end close",
    "deferred revenue", "recognize revenue",
    "SaaS metrics", "MRR calculation", "ARR waterfall",
    "DSO days sales outstanding",
]
```

---

## Secrets (`.env.example`)

Mirror the Reviews Scraper pattern exactly, minus the Reddit API keys:

```
# --- LLM (free tier) ---
GROQ_API_KEY=

# --- Storage (free tier) ---
SUPABASE_URL=
SUPABASE_KEY=

# --- Output routing ---
SLACK_WEBHOOK_COMPETITORS=
SLACK_WEBHOOK_LEADS=
SLACK_WEBHOOK_ICP=
SLACK_WEBHOOK_DIGEST=
SLACK_WEBHOOK_DEFAULT=
SLACK_WEBHOOK_HEALTH=   # optional: for pipeline failure alerts

# --- Polite scraping ---
REDDIT_RSS_USER_AGENT=zenskar-marketing-monitor/1.0 (contact: priyam.s@zenskar.com)
```

No `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` — deliberately absent. No `SERPER_API_KEY` in v1 — deferred to v2.

---

## Scheduling

`.github/workflows/monitor.yml` — single cron `*/30 * * * *` → `python main.py`. Concurrency group `monitor-${{ github.ref }}` prevents overlapping runs (if a 30-min pass runs long, the next one is skipped rather than piling up).

`.github/workflows/weekly-digest.yml` — cron `0 9 * * 1` (Monday 09:00 UTC). Runs `python digest.py`, then commits the generated `reports/YYYY-WW.md` back to the repo on a bot-authored commit.

Both support `workflow_dispatch` for manual trigger (same as Reviews Scraper's `monitor.yml`).

**GitHub Actions free-tier budget check:** 48 real-time runs/day × ~3 min/run × 30 days = ~4320 min/mo. This exceeds the 2000-min free tier for private repos.

**Recommended resolution: make the repo public.** Actions minutes are unlimited on public repos, and this is marketing tooling with zero secret content in the repo itself (all credentials live in GitHub Actions secrets). Your Reviews Scraper likely runs the same way.

If a public repo is a non-starter (e.g., the config file's keyword list is sensitive competitive intelligence), the free-tier fallback is cron `0 * * * *` (hourly, ~1440 min/mo) which still achieves 1–2 hour end-to-end latency.

---

## Cost Estimate — v1 is $0/month

| Line item | Calculation | Monthly |
|---|---|---|
| Reddit RSS (discovery) | ~60 RSS fetches × 48 passes/day = 2880 reqs/day. Free. | **$0** |
| YARS (enrichment) | ~10 post-enrichments per run × 48 runs/day = ~500/day, rate-limited to 1 req per 6s. Free. | **$0** |
| Groq (GPT-OSS 120B) | Stage-1 on ~60 candidates/run + stage-2 on ~5 survivors/run ≈ 50K req/mo; within 14.4K/day per-key free tier after rate-limit pacing, or use two rotating free keys. | **$0** |
| Supabase | <50 MB DB, <100 MB bandwidth/mo — far inside free tier | **$0** |
| GitHub Actions | Public repo → unlimited minutes (see Scheduling section) | **$0** |
| Slack webhooks | Zero-cost for outbound | **$0** |
| **Total** | | **$0 / mo** |

### Merit-gated v2 upgrades

Once v1 has proven marketing value — measured in lead replies booked, competitor intel acted on, or ICP insights referenced — these are the next investments in priority order:

1. **Serper daily recall sweep** (~$15/mo) — catch mentions in subs we don't monitor
2. **Residential proxy pool** for YARS (~$10/mo) — only if GH Actions IP rotation stops being sufficient
3. **HubSpot / CRM integration** (engineering time) — auto-create lead records from high-confidence `bucket='lead'` hits

### Knobs if even $0 v1 creeps toward paying

- Cache Groq stage-1 results by `(normalised_title_hash)` to skip re-classifying cross-posts and reposts
- Drop monitor cron from `*/30` to `0 * * * *` (hourly) if Groq free tier strains
- Move YARS user-profile TTL from 30 days to 90 days to reduce enrichment volume

---

## Legal / ToS Considerations

Documented in `docs/superpowers/specs/2026-04-24-reddit-scraping-design.md`:

- **Reddit RSS** — publicly served RSS feeds with respectful rate-limiting, identifiable User-Agent, no auth circumvention. Reddit's ToS prohibits "automated access except through the API" in strict reading, but RSS is the canonical public-feed protocol and is widely used. We do not scrape login-walled or private content.
- **YARS (`.json` scraping)** — uses the `.json` suffix on Reddit URLs, a documented public surface historically intended for developers. In 2023 Reddit restricted *high-volume* unauthenticated access; we operate far below that threshold (1 req per 6s, ~500 reqs/day). Identifiable User-Agent is set. MIT-licensed library, vendorable if upstream breaks.
- **PullPush** — community archive of public Reddit data; usage is at the user's discretion; Reddit has publicly objected but not enforced against personal/small-scale use. Only used for on-demand historical backfill, not production monitoring.

If Reddit's legal team ever raises an objection, PullPush goes offline, or YARS breaks, we swap the affected source in `sources/` without touching classification, storage, or output. That's the architectural payoff of separating `sources/` from everything else.

---

## Critical Files to Create

| Path | Purpose |
|---|---|
| `main.py` | Orchestrator for 30-min monitor pass |
| `backfill.py` | On-demand historical pull via PullPush |
| `digest.py` | Weekly rollup generator |
| `config.py` | Keywords, subreddits, competitors, intent phrases |
| `models.py` | `RedditHit`, `EnrichedHit`, `Classification`, `UserHints` dataclasses |
| `db.py` | Supabase wrapper (mirror pattern from `Zenskar Reviews Scraper\db.py`) |
| `sources/rss.py` | Layer 1 discovery: subreddit new RSS + global search RSS |
| `sources/yars_enrich.py` | Layer 2 enrichment: YARS wrapper with rate limiter + user-hint cache |
| `sources/pullpush.py` | Historical-only backfill |
| `classify/relevance.py`, `classify/bucket.py`, `classify/prompts.py` | Groq classification pipeline |
| `outputs/slack.py`, `outputs/digest_renderer.py` | Output routing |
| `requirements.txt` | `feedparser`, `requests`, `python-dotenv`, `groq`, `supabase`, `pytest`, `pytest-mock`, `yars @ git+https://github.com/datavorous/yars.git` |
| `.env.example` | Secrets template (see above) |
| `.github/workflows/monitor.yml`, `weekly-digest.yml` | Cron schedules |
| `.claude/settings.local.json` | Copy permissions from Reviews Scraper |
| `docs/superpowers/specs/2026-04-24-reddit-scraping-design.md` | Full spec, committed |
| `tests/...` | pytest suite (RSS parser, YARS mocking, dedupe, classification round-trip, Slack routing) |

## Existing Utilities to Reuse (by pattern, not direct import)

- `D:\Projects\Zenskar Reviews Scraper\db.py` — Supabase client setup pattern; copy the init boilerplate.
- `D:\Projects\Zenskar Reviews Scraper\slack.py` — Slack webhook poster; adapt for multi-channel routing.
- `D:\Projects\Zenskar Reviews Scraper\sentiment.py` — Groq client initialisation; reuse the `get_groq_client()` pattern.
- `D:\Projects\Zenskar Reviews Scraper\.github\workflows\monitor.yml` — CI template; copy structure, swap cron and entrypoint.
- `D:\Projects\Zenskar Reviews Scraper\.claude\settings.local.json` — Claude Code permission allowlist; copy, adjust paths.

Because the user chose "standalone, don't share code," we copy patterns rather than importing — this matches the Reviews Scraper's own convention of flat Python modules.

---

## Verification Plan

**End-to-end smoke test (run locally before first GH Actions cron):**

1. `pip install -r requirements.txt`
2. Fill `.env` with real keys (Supabase, Groq, one Slack webhook).
3. Run Supabase migrations: execute the four `create table` statements in the Supabase SQL editor.
4. `python main.py --dry-run` — prints what it would fetch/enrich/classify/alert without writing to DB or Slack.
5. `python main.py` — one real pass. Expect: several new rows in `reddit_hits`, a handful in `reddit_classifications`, 1–5 Slack messages in the test channel. Should complete in 3–10 minutes (bounded by YARS rate limiter).
6. Manually verify: are the Slack alerts actually relevant? Are ICP hints plausible (the user really does post in CFO-ish subs)? If signal quality is off, iterate on `classify/prompts.py`.
7. `python backfill.py --keyword "Zuora" --from 2024-01-01 --to 2024-01-07 --dry-run` — confirm PullPush returns results.
8. `python digest.py --week 2026-W17 --dry-run` — confirm digest renders against current Supabase data.

**Unit tests (pytest):**
- `test_sources_rss.py` — parse `fixtures/rss_sample.xml` and assert `RedditHit` fields are populated; assert keyword post-filter correctly drops loose tokeniser matches.
- `test_sources_yars_enrich.py` — mock `yars.YARS.scrape_post_details` and `scrape_user_data`, assert rate limiter enforces 6-second spacing, assert 429 → graceful fallback to RSS-only hit.
- `test_classify_bucket.py` — mock Groq response (JSON fixture), assert bucket + extracted fields round-trip correctly.
- `test_db_dedupe.py` — insert a hit twice, assert second insert is a no-op (upsert semantics); insert a user hint, assert 30-day TTL enforcement.
- `test_outputs_slack.py` — mock `requests.post`, assert bucket→webhook routing.

**CI gate:**
- `monitor.yml` runs `pytest` before `python main.py`. First failure = no polling that run.

**Ongoing health check:**
- Weekly digest logs counts per bucket. If competitor count = 0 for a week, something's likely broken upstream (RSS blocked, YARS banned, Groq exhausted).
- Monitor posts a per-run health message to `SLACK_WEBHOOK_HEALTH` summarising: candidates discovered, candidates passing stage-1, YARS success/failure rate, total classifications, alerts posted. First few days of running, watch this closely.

---

## Open Questions for the User (defer to implementation)

None blocking. The following can be finalised during implementation without reopening the plan:
- Exact Slack channel names and webhook URLs.
- Final keyword/subreddit list (starter list above is a reasonable v1; expect to iterate weekly).
- Whether to include Hacker News as a secondary source in v2 (explicit non-goal for v1).
