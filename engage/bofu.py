"""BOFU content catalog — the knowledge base the comment drafter cites from.

Each entry distills a Zenskar bottom-of-funnel page (/alternatives/*,
/comparison/*, /buyers-guide/*) into a few VERIFIED factual one-liners plus the
competitors and intents it serves. When a high-intent thread names one of these
competitors (or matches an intent), the relevant facts are injected into the
draft prompt so the comment is accurate and specific instead of hand-wavy.

The facts here are sourced from Zenskar's own published comparison pages. They
are claims Zenskar makes publicly, so attributing them in a DISCLOSED comment
('i work at zenskar') is honest. They must NOT be presented as neutral
third-party fact from an undisclosed account — the drafter's disclosure rule and
quality gate enforce that.

Keep facts concrete and falsifiable (numbers, timelines, specific missing
features). Vague positioning ('most flexible', 'AI-native') is useless as
grounding and reads as marketing. Refresh when the source pages change.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BofuEntry:
    slug: str
    url: str
    competitors: tuple[str, ...]          # canonical names (match config.COMPETITORS)
    intents: tuple[str, ...]              # free-text intent tags for pain matching
    facts: tuple[str, ...]                # verified, concrete, citable one-liners
    target_subs: tuple[str, ...] = field(default=())  # where a comment fits naturally


CATALOG: tuple[BofuEntry, ...] = (
    BofuEntry(
        slug="alternatives/chargebee",
        url="https://www.zenskar.com/alternatives/chargebee",
        competitors=("Chargebee",),
        intents=("usage-based billing", "metered billing", "complex pricing", "alternative"),
        facts=(
            "chargebee's catalog is flat-list only (flat fee, per-unit, tiered, volume, "
            "stair-step); hybrid/ramp/bespoke contracts need engineering workarounds",
            "no built-in metering module, and usage ingestion is capped around 5,000 events/sec",
            "one invoice template per site, no consolidation/splitting, manual proration",
            "salesforce/netsuite/intacct integrations are paid add-ons ($100-130/mo) and often one-way",
            "struggles with ASC 606/IFRS 15; rigid period locking makes schedule adjustments hard",
        ),
        target_subs=("SaaS", "startups", "fintech", "revenueoperations"),
    ),
    BofuEntry(
        slug="alternatives/zuora",
        url="https://www.zenskar.com/alternatives/zuora",
        competitors=("Zuora",),
        intents=("enterprise billing", "implementation", "migration", "alternative"),
        facts=(
            "zuora implementations typically run 6-9+ months with dedicated resources",
            "most pricing changes need a developer; custom models break down fast",
            "limited native reporting, usually needs a third-party analytics layer",
            "total cost escalates unpredictably; entry pricing is enterprise-tier",
        ),
        target_subs=("SaaS", "fintech", "revenueoperations", "CFO"),
    ),
    BofuEntry(
        slug="alternatives/maxio",
        url="https://www.zenskar.com/alternatives/maxio",
        competitors=("Maxio", "SaaSOptics", "Chargify"),
        intents=("billing rev rec sync", "saas metrics", "alternative"),
        facts=(
            "billing and rev rec came from a merger (chargify + saasoptics) and don't "
            "sync cleanly; usage, invoices, payments drift out of sync",
            "metering is the weak spot; can't do prepaid usage-based billing well",
            "implementation takes months with a steep learning curve",
        ),
        target_subs=("SaaS", "revenueoperations", "fintech"),
    ),
    BofuEntry(
        slug="comparison/stripe-billing-vs-zuora",
        url="https://www.zenskar.com/comparison/stripe-billing-vs-zuora",
        competitors=("Zuora",),  # Stripe Billing intentionally excluded from engagement
        intents=("billing rev rec separation", "developer-owned billing"),
        facts=(
            "tools where billing and rev rec are separate modules force monthly manual "
            "reconciliation; that's the recurring failure mode at close",
            "developer-owned billing means finance can't change pricing without engineering",
        ),
        target_subs=("SaaS", "revenueoperations"),
    ),
    BofuEntry(
        slug="buyers-guide/usage-based-billing-software",
        url="https://www.zenskar.com/buyers-guide/usage-based-billing-software",
        competitors=(),
        intents=("usage-based billing", "metered billing", "hybrid pricing",
                 "tool selection", "billing recommendations"),
        facts=(
            "the real test for any usage-billing tool is metered usage interacting with "
            "commits and minimums; demo it on your three gnarliest contracts, not the happy path",
            "evaluate no-code pricing config separately from metering; many tools meter "
            "but still need a developer for every pricing change",
            "decouple rev rec from billing in your eval; usage-based ASC 606 is where most tools thin out",
        ),
        target_subs=("SaaS", "startups", "fintech", "revenueoperations", "Accounting"),
    ),
)


def grounding_for(competitors: list[str], pain_points: list[str], title: str) -> list[str]:
    """Return the most relevant BOFU facts for a candidate. Matches on named
    competitor first (highest precision), then falls back to intent/pain tokens
    appearing in the pain points or title. Capped so the prompt stays focused."""
    comp_lower = {c.lower() for c in competitors}
    haystack = " ".join(pain_points + [title]).lower()

    facts: list[str] = []
    seen: set[str] = set()

    def _add(entry: BofuEntry) -> None:
        for f in entry.facts:
            if f not in seen:
                seen.add(f)
                facts.append(f)

    # 1) competitor-name matches
    for entry in CATALOG:
        if entry.competitors and comp_lower & {c.lower() for c in entry.competitors}:
            _add(entry)

    # 2) intent/pain matches — but only from GENERAL entries (no competitor of
    # their own). When the thread named no competitor, we want neutral selection
    # advice, not competitor-specific digs the model might introduce unprompted.
    if not facts:
        for entry in CATALOG:
            if entry.competitors:
                continue
            if any(intent in haystack for intent in entry.intents):
                _add(entry)

    return facts[:5]
