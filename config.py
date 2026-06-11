TARGET_SUBREDDITS = [
    "SaaS", "startups", "Entrepreneur", "SaaStr",
    "accounting", "Accountant", "FPandA",
    "finance", "CFO", "Controller", "revenueoperations",
    "fintech", "payments",
    "sysadmin", "smallbusiness",
    "salesforce", "netsuite", "quickbooks",
]

# Canonical competitor names for classification + digest rollups.
COMPETITORS = [
    "Zenskar",
    "Zuora", "Maxio", "Chargify", "SaaSOptics",
    "Stripe Billing", "Chargebee", "Recurly",
    "Ordway", "Metronome", "Tabs", "BillingPlatform",
    "Sage Intacct", "ZoneBilling",
]

# Terms we actually feed to Reddit search.rss. Some competitors need
# disambiguation — 'Tabs' alone matches guitar tabs / browser tabs /
# spreadsheet tabs and floods us with junk. 'Metronome' without 'billing'
# matches music-related posts. These forms are narrower; the canonical
# name still appears in COMPETITORS for classification/reporting.
COMPETITOR_SEARCH_TERMS = [
    "Zenskar",
    "Zuora", "Maxio", "Chargify", "SaaSOptics",
    "Stripe Billing", "Chargebee", "Recurly",
    "Ordway", "Metronome billing", "Tabs.inc", "Tabs billing",
    "BillingPlatform", "Billing Platform",
    "Sage Intacct", "ZoneBilling", "Zone Billing",
]

INTENT_PHRASES = [
    "usage-based billing", "usage based pricing", "metered billing",
    "revenue recognition software", "ASC 606 software",
    "billing automation platform", "subscription billing platform",
    "alternative to Chargebee", "alternative to Zuora", "alternative to Maxio",
    "Chargebee vs", "Zuora vs", "Stripe Billing vs",
    "replacing Stripe Billing", "migrating from Zuora",
    "billing software recommendations", "rev rec tool",
]

# Real phrases CFOs / controllers / RevOps actually type when frustrated.
# Heavy bias toward operational pain points that map to Zenskar capabilities.
ICP_PAIN_PHRASES = [
    # Month-end close / RevRec
    "month-end close took", "month end close hell", "close the books",
    "deferred revenue spreadsheet", "deferred revenue tracking",
    "ASC 606 compliance", "IFRS 15 compliance",
    "rev rec automation", "revenue recognition spreadsheet",
    "unbilled revenue", "revenue waterfall",
    # Usage / hybrid billing
    "usage-based billing nightmare", "metered billing setup",
    "usage data ingestion billing", "billable metrics",
    "hybrid pricing model", "tiered usage pricing",
    "credit-based billing", "consumption pricing",
    # Migration / pain with current tools
    "outgrew Stripe Billing", "outgrew Chargebee", "outgrew Zuora",
    "migrating off Stripe Billing", "leaving Chargebee",
    "moving off Zuora", "moved off Recurly",
    "billing software too expensive", "% of revenue pricing",
    # Operational / engineering pain
    "billing engineer time", "finance ops automation",
    "custom billing logic", "billing edge cases",
    "subscription management mess",
    # Buyer titles + advice
    "CFO billing recommendation", "controller billing advice",
    "RevOps billing tool", "FP&A revenue automation",
    "head of finance billing", "head of revenue accounting",
]

# Auto-generated query variants. Each competitor turns into N search queries
# covering common phrasings buyers use when they're researching alternatives.
_COMPETITOR_VARIANT_TEMPLATES = [
    "{x} alternative", "{x} alternatives", "alternatives to {x}",
    "leaving {x}", "moved off {x}", "switched from {x}",
    "{x} vs", "{x} migration", "replacing {x}",
    "{x} sucks", "{x} is bad", "frustrated with {x}",
    "{x} pricing complaint", "{x} doesn't support",
]


def _generate_competitor_variants(canonical_names: list[str]) -> list[str]:
    """Produce 'X alternative', 'leaving X', etc. for each competitor.
    Skips Zenskar (we don't search for our own alternatives)."""
    out = []
    for name in canonical_names:
        if name.lower() == "zenskar":
            continue
        for tpl in _COMPETITOR_VARIANT_TEMPLATES:
            out.append(tpl.format(x=name))
    return out


COMPETITOR_VARIANTS = _generate_competitor_variants(COMPETITORS)

ICP_TOPICS = [
    "close the books", "month end close",
    "deferred revenue", "recognize revenue",
    "SaaS metrics", "MRR calculation", "ARR waterfall",
    "DSO days sales outstanding",
]

ICP_SUBS = {
    "accounting", "accountant", "fpanda", "cfo", "controller",
    "finance", "revenueoperations", "fintech",
}

USER_HINT_TTL_DAYS = 30
YARS_MIN_INTERVAL_SECONDS = 6.0
PROMPT_VERSION = "v1"

# --- Engagement drafting (CI side) + posting (local poster) -----------------
# Drafter runs in the daily monitor workflow right after classification, so
# drafts land on Telegram at ~09:30 IST and get posted across the day.
MAX_DRAFTS_PER_RUN = 6        # Telegram queue size per day; matches the 5-6/day ceiling
DRAFT_LOOKBACK_HOURS = 30     # slight overlap with the daily cron so nothing falls in a gap

# Poster pacing. The local task fires every ~30 min; these knobs turn that
# into an irregular, human-ish posting pattern instead of a metronome.
POSTER_DAILY_CAP = 5          # hard ceiling on posts per rolling 24h
POSTER_ACTIVE_HOURS = (9, 23) # local hours posting is allowed (IST on the host)
POSTER_SKIP_PROBABILITY = 0.3 # random no-op ticks break up the cadence
MAX_DRAFT_AGE_HOURS = 36      # threads go cold; stale approved drafts get parked

# Freshness gate at SELECTION time (not just post time). Engagement only has
# value on live threads — a 4-day-old thread has stopped getting eyeballs and a
# new top-level comment just looks like necro-posting. Never draft past this.
MAX_CANDIDATE_AGE_HOURS = 48

# Competitors to EXCLUDE from engagement drafting (intel capture still records
# them; we just don't comment on their threads). Stripe Billing threads are
# dominated by Stripe-the-processor / Stripe-stock / generic Stripe API chatter,
# so commenting there draws wrong-reason scrutiny for little ICP payoff.
ENGAGE_EXCLUDE_COMPETITORS = {"Stripe Billing"}

# 'Tabs' is the billing vendor but the bare word floods in from guitar tabs,
# browser tabs, spreadsheet tabs. Two-layer guard for engagement:
#  1) hard drop anything from a music/instrument sub (the QA check),
#  2) for a Tabs-only competitor match, require a billing-context token in the
#     title before we'll draft on it.
MUSIC_SUBS = {
    "guitar", "guitarlessons", "guitars", "bass", "bassguitar", "music",
    "musictheory", "piano", "drums", "ukulele", "luthier", "songwriting",
    "musicians", "guitarplaying", "fingerstyle", "tabs",
}

TABS_BILLING_CONTEXT_TOKENS = {
    "billing", "invoice", "invoicing", "revenue", "rev rec", "saas",
    "pricing", "subscription", "subscriptions", "metering", "usage",
    "chargebee", "maxio", "zuora", "stripe", "collections", "ar", "o2c",
    "finance", "accounting", "startup",
}

# Per-run budget caps. First-run-on-empty-DB can see 500+ candidates; without
# caps, stage-1 Groq + YARS rate-limiting can blow past the CI timeout.
# Excess candidates are simply left for the next cron tick (they're not
# inserted into reddit_hits, so they get reconsidered).
MAX_STAGE1_CALLS_PER_RUN = 250
# Stage-2 uses the 120B model with a 200K/day token bucket. Average
# stage-2 call burns ~3K tokens (input + JSON output), so 50 calls =
# ~150K — leaves headroom for future bigger inputs without blowing the daily
# limit. Tightened from 80 after a run hit 117% usage.
MAX_STAGE2_CALLS_PER_RUN = 50

# Multi-source per-run query budgets. Each query = 1 HTTP call. Tuned
# conservatively so a single run stays under cron's 30-min ceiling and
# under each provider's free-tier daily limit.
MAX_HN_QUERIES_PER_RUN = 30           # Algolia: free, generous, ~10 results each
MAX_SO_QUERIES_PER_RUN = 8            # Stack Exchange: 300/day unauthenticated
MAX_SERPER_QUERIES_PER_RUN = 50       # serper.dev: paid; cap for predictable cost
MAX_REDDIT_COMMENT_FEEDS_PER_RUN = 18 # one per ICP sub

# Source priority — used to sort multi-source candidates before stage-1 so
# higher-signal feeds get the LLM budget first when caps bite.
#
# Logic: pre-filtered + ICP-context-restricted sources rank highest because
# their candidates are usually relevant before stage-1 even sees them. HN
# ranks below comments-RSS because HN search is full-text without any
# domain pre-filter — a "Chargebee" query catches every HN story mentioning
# Chargebee, including offhand mentions in unrelated threads.
SOURCE_PRIORITY = {
    "google_reddit":         1.0,   # SERP snippet contains exact match text
    "reddit_comments_rss":   0.85,  # keyword pre-filtered, in ICP subs only
    "hacker_news":           0.75,  # broad full-text match, less signal density
    "stackoverflow":         0.7,   # tag-restricted; narrow domain
    "rss_search":            0.6,   # title-only match
    "rss_sub":               0.4,   # broadest, weakest signal
}
