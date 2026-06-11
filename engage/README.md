# Engagement: draft → Telegram approval → auto-post

Hands-off Reddit engagement for **one** real, disclosed account. The only
manual step is tapping 👍 / 👎 in Telegram. Everything else runs unattended.

```
GitHub Actions (daily, existing)     Your phone           Local machine (scheduled)
────────────────────────────────     ──────────           ─────────────────────────
main.py: discover → classify →   →   (nothing)
  alert to Slack  (unchanged)

                                                           draft_comments.py  (once/day)
                                                             pick candidates from Supabase
                                                             fetch live old.reddit context
                                                             Gemini draft + quality gate
                                                             send to Telegram  ───────────┐
                                     you tap 👍/👎  ◄──────────────────────────────────────┘
                                          │
                                          ▼
                                                           engage/approval.py  (every ~20m)
                                                             read taps, post approved drafts
                                                             via old.reddit Playwright poster
                                                             verify + mark engaged
```

## Why the engage half runs locally, not in CI

`engage/thread_context.py` and `engage/poster.py` both hit Reddit directly.
Reddit Cloudflare-blocks datacenter IPs (the reason the scraper uses RSS, see
`db.py`/clients notes), and the poster needs a persistent logged-in browser
profile that a fresh CI sandbox can't hold. So the local machine (residential
IP + saved session) runs drafting and posting; CI keeps doing only
discover/classify/alert.

## One-time setup (local machine)

1. Install deps incl. the browser:
   ```
   pip install -r requirements.txt
   python -m playwright install chromium
   ```
2. Apply the drafts table to the Reddit Supabase project (`nihyjwjrqfscwfcgbmqs`):
   `migrations/20260611_create_reddit_drafts.sql`.
3. Create a Telegram bot via @BotFather, get the token. Send the bot any
   message, then read your chat id from
   `https://api.telegram.org/bot<TOKEN>/getUpdates`.
4. Seed the logged-in browser session (opens a real window, log in by hand):
   ```
   python -m engage.seed_login
   ```
5. Fill `.env` (see below).

## .env additions

```
GEMINI_API_KEY=...            # AI Studio key (free tier ok)
GEMINI_MODEL=gemini-flash-latest
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...          # your personal chat id
# Reddit pipeline Supabase (same project the scraper writes to):
SUPABASE_URL=...
SUPABASE_KEY=...
REDDIT_RSS_USER_AGENT=...     # reused by thread_context fetches
# optional overrides:
# REDDIT_PROFILE_DIR=...      # default: ./.reddit-profile
# TELEGRAM_OFFSET_FILE=...    # default: ./.telegram_offset
```

## Running

- **Draft once a day** (Task Scheduler, e.g. 09:30 IST after the CI run):
  `python draft_comments.py`
- **Process approvals + post every ~20 min** (Task Scheduler):
  `python -m engage.approval`

Both are safe to run repeatedly; state lives in Supabase. The approval tick
posts at most one comment, honors `POSTER_*` pacing knobs in `config.py`
(active hours, daily cap, random skip), and parks stale drafts.

## Safety properties

- **Disclosure-enforced.** The drafter prompt defaults to pure-help; any
  Zenskar mention must be disclosed ("i work at zenskar"). The deterministic
  `quality_gate` rejects undisclosed mentions and AI tells (em-dashes,
  marketing words, `not just X` construction) before a draft ever reaches you.
- **No double-posts.** A draft is flipped to `posting` *before* submit and is
  never auto-retried from `posting` or `needs_check`. The poster verifies the
  comment rendered (reads its permalink back) before marking `posted`.
- **One account, by design.** This automates a single disclosed account.
  Multi-account posing is out of scope (it's astroturfing and now also
  violates Reddit's Responsible Builder policy).

## Status lifecycle (reddit_drafts.status)

`pending` → 👍 `approved` → `posting` → `posted`
`pending` → 👎 `skipped` (+ reddit_engaged)
`rejected` (model skipped or gate failed; not re-drafted)
`needs_check` (submit unverified or stale; human looks, never auto-retried)
