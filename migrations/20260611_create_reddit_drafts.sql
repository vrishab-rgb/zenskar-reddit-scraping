-- Comment drafts produced by the Gemini drafter and routed through Telegram
-- approval before the local poster publishes them. Lives in the same Supabase
-- project as reddit_hits / reddit_engaged (nihyjwjrqfscwfcgbmqs).
--
-- Status lifecycle:
--   pending     draft sent to Telegram, awaiting a tap
--   approved    user tapped Approve (edited_text set if they replied with a rewrite)
--   skipped     user tapped Skip (also written to reddit_engaged so the MCP
--               candidates tool stops surfacing it)
--   rejected    drafter/quality-gate refused to produce a usable draft;
--               recorded so we don't re-draft the same candidate every run
--   posting     poster claimed the draft and is about to submit — crash-stop
--               state; never auto-retried (double-post protection)
--   posted      live on Reddit; comment_url holds the permalink
--   needs_check submit was clicked but the result couldn't be verified;
--               requires a human look, never auto-retried
create table if not exists reddit_drafts (
  post_id             text primary key,
  permalink           text not null,
  subreddit           text,
  kind                text not null default 'post',  -- post | comment
  title               text,
  draft_text          text not null,
  edited_text         text,
  status              text not null default 'pending',
  model               text,
  prompt_version      text,
  telegram_message_id bigint,
  comment_url         text,
  note                text,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  posted_at           timestamptz
);

create index if not exists reddit_drafts_status_idx
  on reddit_drafts (status);
create index if not exists reddit_drafts_posted_at_idx
  on reddit_drafts (posted_at desc);
