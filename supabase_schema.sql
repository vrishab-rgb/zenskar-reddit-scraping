-- Run this once in the Supabase SQL editor for the Zenskar project.
-- Creates the four tables the Reddit monitor reads and writes.

create table if not exists reddit_hits (
  post_id           text primary key,
  fetched_at        timestamptz not null default now(),
  created_utc       timestamptz not null,
  subreddit         text not null,
  author            text,
  title             text not null,
  body              text,
  permalink         text not null,
  score             int,
  num_comments      int,
  source            text not null,
  matched_keywords  text[] not null default '{}'
);

create index if not exists reddit_hits_created_utc_idx on reddit_hits (created_utc desc);
create index if not exists reddit_hits_subreddit_idx on reddit_hits (subreddit);

create table if not exists reddit_classifications (
  post_id                text primary key references reddit_hits(post_id) on delete cascade,
  bucket                 text not null,
  mentioned_competitors  text[] not null default '{}',
  buyer_persona_hint     text,
  company_size_hint      text,
  pain_points            text[] not null default '{}',
  sentiment              text,
  prompt_version         text not null,
  classified_at          timestamptz not null default now()
);

create index if not exists reddit_classifications_bucket_idx on reddit_classifications (bucket);

create table if not exists reddit_alerted (
  post_id        text primary key references reddit_hits(post_id) on delete cascade,
  bucket         text not null,
  slack_channel  text not null,
  alerted_at     timestamptz not null default now()
);

create table if not exists reddit_user_hints (
  username                   text primary key,
  fetched_at                 timestamptz not null default now(),
  recent_subreddits          text[] not null default '{}',
  account_age_days           int,
  total_karma                int,
  prior_competitor_mentions  text[] not null default '{}',
  is_icp_likely              boolean
);

create index if not exists reddit_user_hints_fetched_at_idx on reddit_user_hints (fetched_at);

create table if not exists reddit_comment_suggestions (
  post_id            text primary key references reddit_hits(post_id) on delete cascade,
  suggested_comment  text not null default '',
  plug_strategy      text not null,
  rationale          text not null default '',
  skip_reason        text,
  prompt_version     text not null,
  created_at         timestamptz not null default now()
);

create index if not exists reddit_comment_suggestions_strategy_idx on reddit_comment_suggestions (plug_strategy);

-- Groq doesn't expose daily token quotas via response headers (only per-minute).
-- We track our own usage by summing usage.total_tokens from each call into this
-- table, keyed by (model, UTC day). Resets implicitly when day rolls over.
create table if not exists groq_daily_usage (
  model        text not null,
  day_utc      date not null,
  tokens_used  bigint not null default 0,
  updated_at   timestamptz not null default now(),
  primary key (model, day_utc)
);
