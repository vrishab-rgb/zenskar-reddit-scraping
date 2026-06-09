# Cowork scheduled task — Zenskar Reddit engagement (daily)

Paste the block below into a **Claude Cowork** scheduled task (run once daily,
e.g. 09:30 IST). Cowork must have: (1) the **Zenskar Marketing MCP** connected,
(2) the **reddit-engagement skill** available, and (3) **Claude for Chrome**
(Claude operating inside the browser) enabled, with Chrome logged into the
engagement Reddit account.

> Note: the MCP only *reads* candidates and records engagement. You (Claude) read
> each live thread **in Chrome** and write every comment. There is no auto-post
> step — you present a queue and post only what the human approves in-session.
> Posting is done by Claude driving the Chrome tab directly (navigate, click,
> type), not via OS-level clipboard/foreground tricks.

---

## The scheduled prompt

```
Run today's Zenskar Reddit engagement pass. Use the `reddit-engagement` skill —
follow it exactly; it has the voice rules, the AR-vs-AP boundary, the pure-help
(no product plug) stance, and the posting mechanics.

Steps:
1. Call `reddit_engagement_candidates(lookback_hours=24, limit=25)` from the
   Zenskar Marketing MCP to pull today's ranked, de-duplicated candidates
   (posts + in-thread comment reply-opportunities the pipeline already
   classified). They're already de-noised and de-duped server-side.

2. Triage to the few genuinely worth a reply (quality over count — the skill's
   triage rules decide). It's normal for a day to yield only 2-3. Hard ceiling
   ~5-6; there is NO quota and NO obligation to hit a number.

3. For each keeper: using Claude for Chrome, navigate to its `permalink` and READ
   the full thread and the existing replies (so you don't repeat what's said and
   you target the right comment), then draft a reply in the skill's native voice.
   Pure help, zero Zenskar mention.

4. Present all drafts to me as an approval queue: for each, show the subreddit,
   a one-line "what this comment adds that isn't already in the thread", the
   permalink, and the draft text. Do NOT post anything yet.

5. After I approve (per-comment), post each by driving the Chrome tab directly:
   for a post, click the comment box; for a comment-reply, click that comment's
   Reply button first. Type the approved text into the composer and submit, then
   confirm the comment actually appears and capture its permalink. Space them
   out; don't burst.

6. For every comment posted, call `reddit_mark_engaged(post_id, comment_url, note)`
   so it stops re-surfacing. Also mark deliberate skips with a short note.

7. End with a short recap: what you posted (with links), what you skipped and why,
   and how many candidates the pull returned.

If today's pull has nothing worth posting, say so and stop — a no-post day is a
valid outcome, not a failure.
```

---

## Operator notes (not part of the prompt)

- **Pacing** is a ceiling set by good threads, not a target. A run that posts 0
  is fine. Bursts of near-identical comments are the spam signal.
- **Posting via Claude for Chrome**: Claude drives the logged-in tab directly, so
  the old OS-clipboard + foreground-window recipe in the skill does NOT apply
  here — navigate, click the composer, type, submit within the tab. (The skill's
  clipboard recipe is the fallback for the non-Cowork, browser-MCP setup.)
- **Confirm before moving on, never blind-retry a submit** (double-post risk).
  After submitting, verify the new comment actually rendered in the thread and
  grab its permalink before the next one. If the composer didn't open or submit
  silently no-op'd, re-open it fresh rather than re-submitting blindly.
- The skill file is the source of truth for voice/AI-tell bans and gold-standard
  examples; this prompt just sequences the daily loop.
