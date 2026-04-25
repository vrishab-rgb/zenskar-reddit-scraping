import json
import os

from groq import Groq

from classify import groq_quota
from classify.prompts import BUCKET_SYSTEM, PROMPT_VERSION, bucket_user_message
from models import Classification, EnrichedHit

_client = None
_VALID_BUCKETS = {"competitor_mention", "lead_signal", "icp_discussion", "noise"}


class BucketRateLimited(Exception):
    """Stage-2 could not run because Groq's 120B quota is exhausted. Caller
    should defer this hit (do NOT upsert, do NOT record classification) so
    the next run after quota reset can retry from scratch."""


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def _comments_snippet(enriched: EnrichedHit, max_count: int = 8) -> str | None:
    if not enriched.comments:
        return None
    parts = []
    for c in enriched.comments[:max_count]:
        body = (c.body or "").strip().replace("\n", " ")
        if not body:
            continue
        parts.append(f"- {body[:400]}")
    return "\n".join(parts) if parts else None


def _user_hint_summary(enriched: EnrichedHit) -> str | None:
    h = enriched.user_hints
    if h is None:
        return None
    lines = []
    if h.recent_subreddits:
        lines.append(f"recent_subreddits={h.recent_subreddits}")
    if h.account_age_days is not None:
        lines.append(f"account_age_days={h.account_age_days}")
    if h.total_karma is not None:
        lines.append(f"total_karma={h.total_karma}")
    if h.prior_competitor_mentions:
        lines.append(f"prior_competitor_mentions={h.prior_competitor_mentions}")
    lines.append(f"is_icp_likely={h.is_icp_likely}")
    return ", ".join(lines) if lines else None


def _fallback_noise(post_id: str) -> Classification:
    return Classification(
        post_id=post_id,
        bucket="noise",
        prompt_version=PROMPT_VERSION,
    )


def classify(enriched: EnrichedHit) -> Classification:
    hit = enriched.hit
    user_msg = bucket_user_message(
        title=hit.title,
        body=hit.body,
        comments_snippet=_comments_snippet(enriched),
        user_hint_summary=_user_hint_summary(enriched),
        matched_keywords=hit.matched_keywords,
    )
    try:
        resp = groq_quota.chat_complete(
            _get_client(),
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": BUCKET_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=500,
            temperature=0,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate_limit" in msg.lower():
            raise BucketRateLimited(msg) from e
        print(f"[bucket] Groq error for {hit.post_id}: {e}")
        return _fallback_noise(hit.post_id)

    bucket = data.get("bucket", "noise")
    if bucket not in _VALID_BUCKETS:
        bucket = "noise"

    return Classification(
        post_id=hit.post_id,
        bucket=bucket,
        mentioned_competitors=list(data.get("mentioned_competitors") or []),
        buyer_persona_hint=data.get("buyer_persona_hint"),
        company_size_hint=data.get("company_size_hint"),
        pain_points=list(data.get("pain_points") or []),
        sentiment=data.get("sentiment"),
        prompt_version=PROMPT_VERSION,
    )
