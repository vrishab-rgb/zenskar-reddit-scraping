---
name: reddit-engagement
description: Run Zenskar's daily Reddit engagement — pull pre-classified candidate posts AND in-thread comments from the marketing MCP, draft genuinely helpful, native-sounding replies (pure help, NO product plug), get approval, post them, and mark them done. Use when asked to find Reddit places to comment, draft Reddit replies in Zenskar's voice, or run the recurring Reddit engagement task.
---

# Reddit Engagement (Zenskar)

Goal: show up as a genuinely helpful practitioner in finance/billing/RevOps/SaaS
communities. Earn standing with useful comments. **No product pitching.** The
payoff is a credible account and topical presence (incl. AI-search citations),
not link-drops.

You (Claude) write every comment. Do **not** use any pre-generated `suggested_comment`
from the pipeline — those came from a weak model and fabricate things. Draft fresh.

## Tools (Zenskar Marketing MCP)

- `reddit_engagement_candidates(lookback_hours=24, include_posts=true, include_comments=true, limit=25, exclude_engaged=true)`
  → ranked non-noise candidates (posts and in-thread comment reply-opportunities)
  the pipeline already found + classified. Each has: `permalink`, `kind`
  (post|comment), `subreddit`, `title`, `body`, `author`, `age_hours`, `bucket`,
  `persona`, `pain_points`, `sentiment`, `mentioned_competitors`.
- `reddit_mark_engaged(post_id, comment_url, note)` → call after you post (or
  deliberately skip) so it stops re-surfacing.

Thread context is NOT in these tools. Always **open the `permalink` in the
browser** before drafting, to read the post fully and the existing replies — so
you don't repeat what's already said and you target the right comment.

## Daily loop

1. `reddit_engagement_candidates(lookback_hours=24)`.
2. Triage to the few genuinely worth a reply (see Triage). Quality over count.
3. For each keeper: open the permalink, read the thread, draft a comment in the
   Voice below.
4. Present the drafts to the human as a queue for approval. Don't auto-post.
5. On approval, post (see Posting). Then `reddit_mark_engaged(post_id, comment_url)`.
6. Mark deliberate skips too, with a short `note`, so they don't reappear.

## Triage — what's worth a comment

Comment when you can add something a practitioner would respect: a specific
operating insight, a real trade-off, a correction, a "here's the gotcha."

Skip when:
- You'd only be restating the post or agreeing with no new substance (padding).
- It's outside genuine knowledge (you'd be guessing → reads as AI slop).
- It's a vendor's own promo/lead-gen thread, a heavily-moderated anti-self-promo
  sub where even disclosed help gets nuked, or already has your account's comment.
- It's off-topic, hostile, or career/exam/salary chatter.

**Boundary — what Zenskar is / is NOT** (you're in pure-help mode so you won't
mention it anyway, but this keeps you from drifting into wrong territory):
Zenskar is **Order-to-Cash / AR** — billing *your customers*, rev rec, collections,
usage metering, entitlements. It is **NOT** accounts payable, vendor/OFAC/sanctions
screening, payment processing/acquiring/settlement, chargebacks, treasury, payroll,
or tax calculation. If a thread is only about that money-OUT / payments-infra side,
it's out of lane.

## Voice — write like a real person, not an AI

- Lowercase-leaning, conversational, first person. Like you typed it on your phone.
- **Lead with 2+ sentences of specific, real advice** before anything else.
- Concrete > generic. "platitudes" (communication is key, visibility matters) are filler.
- 250–700 chars usually. Match the thread's depth (HN/technical subs tolerate longer).

**Hard "AI tell" bans** (people screenshot these and call out bots):
- ❌ em-dashes (—). Use commas, parens, periods.
- ❌ the "not just X, it's Y" / "it isn't X, it's Y" construction. Rephrase.
- ❌ marketing words: leverage, streamline, robust, empower, unlock, "worth looking at", "check out".
- ❌ tidy rule-of-three flourishes, "in today's landscape", exclamation marks, emoji.

**Pure help — no plug.** Default to zero Zenskar mention. Building account
credibility *is* the goal right now. (If a disclosed mention is ever wanted later,
it must say "I'm on the team at Zenskar" — never pose as an unaffiliated customer.
Undisclosed "we use Zenskar" from this account is astroturfing; don't.)

### Gold-standard examples (real, posted)

CPQ thread (standalone vs integrated):
> depends where your complexity actually is. if quoting is the painful part (lots
> of approval steps, discount sign-offs, multi-party deals) a dedicated CPQ like
> dealhub is worth it. if quoting is simple and the mess is really on the billing
> side, usage, commits, ramps, then the integrated one saves you babysitting a sync
> between two systems. tbh what actually bites people is the handoff between the two...

Comment-reply, NetSuite data-bloat (note: it *adds* a new angle — SOX risk — and
references other commenters, proving it read the thread):
> this is the right call, and worth flagging the flip side for OP specifically:
> since you're a public company, be careful with the purge-via-map/reduce idea.
> deleting transaction chain data can break your audit trail and create SOX
> retention problems even if the trial balances still tie...

The test: if you can't say in one sentence what your comment *adds* that isn't
already in the thread, don't post it.

## Pacing

~5–6 genuinely-good comments per day is the ceiling, and it's a ceiling set by
good threads, not a quota. If today only yields 3 worth doing, do 3. Space them
across the day. A burst of near-identical comments in one window is the spam
signal regardless of how human each reads. Mix subs and mix post-vs-comment.

## Posting mechanics

Two setups, depending on how you're driving the browser. **Confirm the comment
actually rendered and grab its permalink before moving on, and never blind-retry
a *submit*** (double-post risk) — that rule holds for both.

### Preferred: Claude for Chrome (the Cowork setup)

When you're operating *inside* Chrome (Claude for Chrome / computer use), drive
the logged-in tab directly:

1. Navigate to the `permalink`.
2. Click the comment box (for a comment-reply, click that comment's **Reply**
   button first to open its inline composer).
3. Type the approved text into the composer and submit.
4. Confirm the new comment appears, grab its permalink, then `reddit_mark_engaged`.

No clipboard or foreground-window tricks are needed — you control the tab.

### Fallback: browser-MCP + OS clipboard

When posting through the browser MCP (not Claude-in-Chrome), Reddit's SPA makes
`type`/`click` flaky and the tab must be the **foregrounded** window or paste and
editor-focus silently fail. Use the clipboard recipe instead:

1. Put the final comment on the clipboard.
2. Click the comment box (Reply button first for a comment-reply).
3. Paste (Ctrl+V).
4. Submit (Ctrl+Enter — Reddit's native submit).
5. Confirm "Comment posted successfully" + the new comment appears, grab its
   permalink, then `reddit_mark_engaged`.

If a composer won't expand, the tab is almost certainly not foregrounded — fix
that before retrying.
