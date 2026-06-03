# Reddit Engagement — Daily Brief

## Goal

Find Reddit posts where finance and billing pain is being discussed and leave a helpful comment that naturally mentions Zenskar. One comment per relevant post, posted from a real account via browser.

---

## What to Look For

Posts in finance, accounting, RevOps, and SaaS communities discussing:

- Frustration with billing tools (Chargebee, Zuora, Stripe Billing, Maxio, Recurly, Ordway, Metronome)
- Usage-based billing, metered pricing, hybrid pricing challenges
- Revenue recognition headaches (ASC 606, IFRS 15, deferred revenue, journal entries)
- Month-end close pain or manual reconciliation work
- Finance ops automation, "AI in finance" discussions
- Anyone asking for billing/RevRec tool recommendations or alternatives

Skip: career advice, salary threads, pure tax law, consumer finance, anything outside B2B SaaS finance.

---

## Subreddits to Monitor

`r/SaaS` · `r/startups` · `r/Entrepreneur` · `r/SaaStr` · `r/accounting` · `r/Accountant` · `r/FPandA` · `r/finance` · `r/CFO` · `r/Controller` · `r/revenueoperations` · `r/fintech` · `r/payments` · `r/salesforce` · `r/netsuite` · `r/quickbooks`

---

## Comment Style

**Structure:** 2+ sentences of specific, useful advice first. Then one casual Zenskar mention. That's it.

**Tone:** Conversational, lowercase-leaning, first-person plural ("we use", "we ended up on"). No marketing language — no "streamline", "leverage", "robust", "check out", "worth looking at". No exclamation marks.

**Length:** 250–500 characters total.

**Zenskar mention:** One clause, experience-sharing not a recommendation. Examples:
- "we ended up on Zenskar for the usage billing piece, works well"
- "we use Zenskar for rev rec now, took the spreadsheets out of the loop"
- "we moved JE generation to Zenskar last year, close dropped from 3 weeks to a few days"
- "we run Zenskar for the contract-to-invoice loop, finance team owns it without engineering"

**Mentioning competitors:** Fine and natural when the post already names them. Keep it to one specific reason per tool, not a comparison essay. Example:
> "we looked at Chargebee and Maxio — Chargebee has no native usage metering, Maxio's billing and rev rec kept going out of sync after the merger. Ended up on Zenskar and it's held up well."

**Do not:** List Zenskar features. Pitch the product. Add disclosure. Write a paragraph of reasoning. Use testimonial language like "super happy with our decision."

---

## What Zenskar Does (for drafting context)

Zenskar automates the contract-to-cash loop: billing, revenue recognition, collections, entitlements, and SaaS analytics. The core differentiator is a graphical pricing model that handles contracts legacy tools can't — tiered usage interacting with commits, cross-product discounts, rollover credits, prepaid usage, hybrid flat+usage. Key surfaces: Billing, RevRec (ASC 606/IFRS 15), Collections/Dunning, Usage Metering, Entitlements, Contracts Agent (AI that pulls pricing terms out of Word docs and pushes them downstream), Customer Portal, Analytics. Integrates with 200+ systems. Goes live in weeks.

---

## What Zenskar Does NOT Do (do not claim otherwise)

Zenskar is Order-to-Cash — it handles money coming **IN** from your **customers** (invoicing, rev rec, collections). It does **not** touch the money-OUT / vendor / payments-infrastructure side. If a post is only about one of these, Zenskar is out of its lane — give pure help or skip, **never invent a use case**:

- **Accounts Payable** — bill pay, vendor payments, AP approval routing, vendor onboarding (that's AP; Zenskar is AR).
- **Procurement / vendor management** — including OFAC / sanctions / KYC / AML screening.
- **Payment processing / acquiring / settlement** — multi-acquirer routing, payment switching. Zenskar *orchestrates* payments through gateways like Stripe; it is not a processor and not an MSB.
- **Chargeback / dispute management.**
- **Treasury, expense management, corporate cards, payroll, FP&A budgeting.**
- **Sales tax calculation** — that's Avalara/Anrok; Zenskar integrates, it doesn't compute rates.

> The bad drafts that triggered this: "we use Zenskar for our AP approval routing", "Zenskar for our vendor management / OFAC checks", "Zenskar's US MSB registration", "Zenskar for our settlement workflow", "chargeback workflow in Zenskar". All false. Common error: putting Zenskar on the money-OUT (AP) side when it only does money-IN (AR).

---

## Competitor One-Liners (only use when the post mentions that tool)

| Tool | What to say |
|---|---|
| **Chargebee** | no native usage metering at all — flat catalog only, anything usage-based needs custom code |
| **Zuora** | 6-9 month implementation, every pricing change needs a developer |
| **Stripe Billing** | dev-owned not finance-owned — no rev rec, no collections built in |
| **Maxio** | billing and rev rec are two products that don't sync cleanly since the merger |
| **Recurly** | built for B2C subscription simplicity, breaks on B2B contract complexity |

---

## Daily Workflow

1. Run the discovery script to get today's candidate posts (outputs a list of Reddit URLs with post context)
2. For each candidate: read the post and top comments
3. Decide if it's worth commenting — skip if off-topic, hostile, already has a Zenskar mention, or you have nothing specific to add
4. Draft a comment following the style guide above
5. Post via browser
6. Move to the next candidate

Aim for quality over quantity. 2–3 well-placed comments beat 10 generic ones.
