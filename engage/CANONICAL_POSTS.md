# Canonical Reddit post brief (for the Cowork writer)

A scheduled Cowork agent uses this to write **one** canonical Reddit post per
run, then delivers it to Slack:

```
python publish_post.py --file <draft>.md
```

A human reviews in Slack and posts it manually from a **founder or warmed
nurture account**. These are NOT auto-posted — new self-promo submissions get
removed by most subs, so a person picks the moment, the exact sub, and confirms
the account has standing.

## Pick the next topic (rotate, don't repeat)

Source material is the BOFU catalog in `engage/bofu.py` (verified facts from
Zenskar's own comparison pages). Rotate across these angles so the account
doesn't post the same shape twice in a row:

| Angle | Format | Source entry | Lands best in |
|---|---|---|---|
| competitor-vs-competitor teardown | "evaluated X vs Y for [use case]" | comparison/* | r/SaaS, r/fintech |
| opinion / gotcha | "the real reason [thing] breaks is [claim]" | positioning | r/SaaS, r/ExperiencedDevs |
| evaluation matrix | "evaluated N tools for [use case], teardown" | buyers-guide/* | r/SaaS (founder acct) |

Don't write a matrix post two runs running. Vary competitor focus too.

## Voice + hard rules (same as the comment drafter)

- lowercase-leaning, first person, like a practitioner typed it. lead with real
  substance, a trade-off or a gotcha, before anything else.
- **NO em-dashes**, no "not just X, it's Y", no marketing words (leverage,
  streamline, robust, unlock, "worth looking at", "check out"), no exclamation
  marks, no emoji.
- 150-400 words for a post. a comparison can run longer; an opinion post is short.
- **disclosure is mandatory** on any post that names Zenskar: one short clause,
  "full disclosure i work at zenskar so weigh that". never pose as a customer.
- the post must survive WITHOUT the Zenskar line. if it only makes sense as a
  path to "...so use Zenskar", it's an ad, rewrite it. zenskar is a footnote,
  not the thesis.
- only contrast a competitor the post's premise genuinely involves; state only
  facts from `engage/bofu.py` (don't invent specifics).
- respect Zenskar's lane: O2C / billing / rev rec / collections / usage /
  entitlements. never claim AP, payments processing, tax calc, treasury, etc.

## Output format

Write the draft as markdown with front matter:

```
---
title: <the post title as it'll appear on reddit>
subreddit: SaaS
source_url: <the bofu page it draws from>
notes: <e.g. founder account; account needs comment history first>
---
<post body>
```

Then deliver: `python publish_post.py --file <draft>.md`

## Why Slack, not auto-post

Posts are the high-scrutiny, high-ban-risk surface. Slack review keeps a human
in the loop to choose the sub, confirm account standing, and catch anything the
brief missed. The auto-posted channel is COMMENTS (the grounded reply pipeline),
which is what subs actually tolerate.
```
