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

# Per-run budget caps. First-run-on-empty-DB can see 500+ candidates; without
# caps, stage-1 Groq + YARS rate-limiting can blow past the CI timeout.
# Excess candidates are simply left for the next cron tick (they're not
# inserted into reddit_hits, so they get reconsidered).
MAX_STAGE1_CALLS_PER_RUN = 250
MAX_ENRICHMENTS_PER_RUN = 20
# Stage-3 (comment-suggestion) is gated separately. We don't draft for noise,
# and only a fraction of stage-2 outputs are non-noise, so this cap mostly
# bites on first-run. 8B model has ~500K/day; 25 calls/run × 48 runs ≈
# 1200 calls/day, comfortably under quota.
MAX_STAGE3_CALLS_PER_RUN = 25
