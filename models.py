from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RedditHit:
    post_id: str
    subreddit: str
    author: str | None
    title: str
    body: str | None
    permalink: str
    created_utc: datetime
    score: int | None
    num_comments: int | None
    source: str
    matched_keywords: list[str] = field(default_factory=list)


@dataclass
class Comment:
    author: str | None
    body: str
    score: int | None


@dataclass
class UserHints:
    username: str
    recent_subreddits: list[str]
    account_age_days: int | None
    total_karma: int | None
    prior_competitor_mentions: list[str]
    is_icp_likely: bool


@dataclass
class EnrichedHit:
    hit: RedditHit
    comments: list[Comment] = field(default_factory=list)
    user_hints: UserHints | None = None
    enrichment_failed: bool = False


@dataclass
class Classification:
    post_id: str
    bucket: str  # 'competitor' | 'lead' | 'icp' | 'noise'
    mentioned_competitors: list[str] = field(default_factory=list)
    buyer_persona_hint: str | None = None
    company_size_hint: str | None = None
    pain_points: list[str] = field(default_factory=list)
    sentiment: str | None = None
    prompt_version: str = "v1"


@dataclass
class CommentSuggestion:
    post_id: str
    suggested_comment: str  # empty string when the model declines
    plug_strategy: str  # "none" | "soft_mention" | "direct_recommend" | "skip"
    rationale: str
    skip_reason: str | None = None
    prompt_version: str = "v1"
