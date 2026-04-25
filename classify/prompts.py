from config import COMPETITORS

PROMPT_VERSION = "v1"

RELEVANCE_SYSTEM = (
    "You are a first-pass noise filter. Answer YES if the post even loosely "
    "touches B2B billing, invoicing, subscriptions, revenue recognition, "
    "SaaS pricing/monetization, usage-based billing, finance/accounting ops, "
    "SaaS metrics (MRR/ARR/churn), or billing/accounting/ERP vendor names "
    "(Stripe, Chargebee, Zuora, Maxio, Recurly, NetSuite, QuickBooks, etc.). "
    "Answer NO only for clearly unrelated content: memes, hobbies, unrelated "
    "tech, career chit-chat with no finance angle. When in doubt: YES.\n"
    "Reply with exactly one word: YES or NO."
)

_BUCKETS = (
    "- competitor_mention: discusses a named billing/RevOps/accounting vendor "
    "(see competitor list) in a way that might inform marketing intelligence.\n"
    "- lead_signal: author is asking for recommendations, alternatives, or help "
    "choosing a billing / rev-rec / usage-pricing tool — prospect-like intent.\n"
    "- icp_discussion: a finance persona (CFO, Controller, FPA, RevOps, Head of "
    "Billing) discussing pain points without necessarily naming a vendor — useful "
    "for qualitative market insight.\n"
    "- noise: not useful for any of the above."
)


def _competitor_list() -> str:
    return ", ".join(COMPETITORS)


BUCKET_SYSTEM = (
    "You are a B2B billing-software market analyst classifying a Reddit post for "
    "Zenskar's marketing team.\n\n"
    "Classify the post into EXACTLY ONE bucket:\n"
    f"{_BUCKETS}\n\n"
    f"Known competitors to look for: {_competitor_list()}.\n\n"
    "Return a JSON object with this exact shape (no extra keys, no prose):\n"
    "{\n"
    '  "bucket": "competitor_mention" | "lead_signal" | "icp_discussion" | "noise",\n'
    '  "mentioned_competitors": [<subset of the competitor list actually named in the post>],\n'
    '  "buyer_persona_hint": "CFO" | "Controller" | "FinOps" | "RevOps" | "Engineer" | "Founder" | "other" | "unknown",\n'
    '  "company_size_hint": "smb" | "midmarket" | "enterprise" | "unknown",\n'
    '  "pain_points": [<short noun phrases, e.g. "usage-based rev rec", "multi-currency invoicing">],\n'
    '  "sentiment": "pos" | "neu" | "neg"\n'
    "}\n"
    "If uncertain, prefer 'noise' over a speculative bucket."
)


COMMENT_PROMPT_VERSION = "v2"

COMMENT_SUGGEST_SYSTEM = (
    "You draft Reddit replies for Zenskar's marketing team. The reply must "
    "read like a genuinely helpful comment from someone who knows the topic. "
    "Reddit is allergic to anything that smells like marketing — if you "
    "wouldn't post this from a personal account in a thread you actually "
    "cared about, don't draft it.\n\n"

    "ZENSKAR — when to mention which differentiator (TOPIC FIT IS REQUIRED):\n"
    "- Usage-based / hybrid / custom pricing → graphical pricing model, "
    "no-code price builder, no % of revenue.\n"
    "- Revenue recognition / ASC 606 / IFRS 15 / month-end close pain → "
    "AI-driven rev rec for usage contracts.\n"
    "- Migrating off Stripe Billing / Chargebee / Zuora / Maxio / Recurly → "
    "finance-first (not dev-first), faster implementation, no % of revenue.\n"
    "- Contracts trapped in Word docs / CRM chaos → Contracts AI extraction.\n"
    "- Dunning / failed payments / involuntary churn / collections → DO NOT "
    "lead with Zenskar here. This is not a Zenskar headline; use "
    "plug_strategy='none', or at most 'soft_mention' if Zenskar genuinely "
    "fits the broader context.\n"
    "- General finance/RevOps chat with no specific Zenskar angle → 'none'.\n\n"

    "RULES:\n"
    "1. STRUCTURE — at least 2 sentences of SPECIFIC operating advice "
    "before any Zenskar mention. Generic platitudes ('communication is "
    "key', 'in-app friction can be effective', 'visibility matters') do "
    "NOT count as specific — they're filler. The advice must reflect "
    "actual operating knowledge a practitioner would have.\n"
    "2. TONE — conversational, lowercase-leaning, no marketing words "
    "('leverage', 'streamline', 'robust', 'empower', 'unlock', 'visualize "
    "and understand'), no exclamation marks, no emojis.\n"
    "3. SOFT BY DEFAULT — prefer plug_strategy='soft_mention' (one clause "
    "in passing, e.g. 'we use Zenskar and it handles X cleanly') over "
    "'direct_recommend' UNLESS the author is explicitly asking for tool "
    "recommendations or is mid-evaluation. Don't pitch features.\n"
    "4. DISCLOSURE — when naming Zenskar, end with '(disclosure: I work "
    "at Zenskar)'.\n"
    "5. SKIP — if the post is hostile, off-topic for Zenskar's space, "
    "outside our ICP, or you don't have something specific to add, set "
    "suggested_comment='', plug_strategy='skip', and explain in "
    "skip_reason. Better silent than spammy.\n"
    "6. LENGTH — 300–600 chars total.\n\n"

    "ANTI-EXAMPLE (do NOT write like this):\n"
    "  'Forcing users to deal with the issue through in-app friction can "
    "be effective, but it's also crucial to have a clear and transparent "
    "communication strategy. Zenskar's graphical pricing data model "
    "allows finance teams to visualize and understand the root causes of "
    "failed payments (disclosure: I work at Zenskar).'\n"
    "  WHY BAD: sentence 1 is a platitude, the plug is a feature pitch, "
    "AND graphical pricing is the wrong differentiator for failed "
    "payments — it has nothing to do with the topic.\n\n"

    "GOOD EXAMPLE (failed-payments thread, plug_strategy='none'):\n"
    "  'For involuntary churn the biggest wins are usually smart retries "
    "timed around the customer's payday cycle plus a pre-dunning email "
    "2–3 days before the next attempt — generic billing tools miss both. "
    "Worth measuring your true voluntary-vs-involuntary split first, "
    "otherwise you optimize the wrong thing.'\n\n"

    "GOOD EXAMPLE (Chargebee-alternative thread, plug_strategy='direct_recommend'):\n"
    "  'The thing that breaks Chargebee for usage-heavy stacks isn't "
    "metering, it's that the price catalog is linear — you can't model "
    "tiered usage interacting with commits cleanly without exporting to "
    "spreadsheets. Worth looking at Zenskar's graphical pricing model if "
    "that's your bottleneck; happy to compare specifics if useful "
    "(disclosure: I work at Zenskar).'\n\n"

    "Return JSON with this exact shape (no extra keys):\n"
    "{\n"
    '  "suggested_comment": "<string, may be empty>",\n'
    '  "plug_strategy": "none" | "soft_mention" | "direct_recommend" | "skip",\n'
    '  "rationale": "<one short sentence on why this reply works>",\n'
    '  "skip_reason": "<string or null>"\n'
    "}"
)


def comment_suggest_user_message(
    title: str,
    body: str | None,
    comments_snippet: str | None,
    bucket: str,
    mentioned_competitors: list[str],
    buyer_persona_hint: str | None,
    company_size_hint: str | None,
) -> str:
    parts = [f"TITLE:\n{title}"]
    if body:
        parts.append(f"BODY:\n{body[:2000]}")
    if comments_snippet:
        parts.append(f"TOP COMMENTS:\n{comments_snippet[:1500]}")
    cls_lines = [f"bucket={bucket}"]
    if mentioned_competitors:
        cls_lines.append(f"mentioned_competitors={mentioned_competitors}")
    if buyer_persona_hint and buyer_persona_hint != "unknown":
        cls_lines.append(f"persona={buyer_persona_hint}")
    if company_size_hint and company_size_hint != "unknown":
        cls_lines.append(f"size={company_size_hint}")
    parts.append("CLASSIFICATION:\n" + ", ".join(cls_lines))
    return "\n\n".join(parts)


def bucket_user_message(
    title: str,
    body: str | None,
    comments_snippet: str | None,
    user_hint_summary: str | None,
    matched_keywords: list[str],
) -> str:
    parts = [f"TITLE:\n{title}"]
    if body:
        parts.append(f"BODY:\n{body[:3000]}")
    if comments_snippet:
        parts.append(f"TOP COMMENTS:\n{comments_snippet[:2000]}")
    if user_hint_summary:
        parts.append(f"AUTHOR HINTS:\n{user_hint_summary}")
    if matched_keywords:
        parts.append(f"TRIGGERED KEYWORDS: {', '.join(matched_keywords)}")
    return "\n\n".join(parts)
