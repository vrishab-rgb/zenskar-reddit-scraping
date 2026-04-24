from config import COMPETITORS

PROMPT_VERSION = "v1"

RELEVANCE_SYSTEM = (
    "You are a Reddit content filter for a billing-software company's marketing team. "
    "Decide whether a post is related to ANY of: billing software, revenue recognition, "
    "subscription pricing, usage-based pricing, metered billing, accounting software, "
    "finance/accounting operations (AR, AP, close, reconciliation), CFO/controller/FPA "
    "topics, or mentions of billing/accounting vendors. "
    "Respond with exactly one word: YES or NO."
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
