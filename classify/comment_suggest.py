"""Stage-3: draft a suggested Reddit reply for non-noise hits.

Mirrors the shape of `classify.bucket`: same Groq client singleton, same
defer-on-429 pattern, same prompt-versioning. Lives on the 8B model so it
doesn't compete with stage-2's 120B daily bucket.
"""
import json

from classify import bucket as bucket_mod
from classify import groq_quota
from classify.prompts import (
    COMMENT_PROMPT_VERSION,
    COMMENT_SUGGEST_SYSTEM,
    comment_suggest_user_message,
)
from models import Classification, CommentSuggestion, EnrichedHit

_MODEL = "llama-3.1-8b-instant"
_VALID_STRATEGIES = {"none", "soft_mention", "direct_recommend", "skip"}


class CommentSuggestRateLimited(Exception):
    """Stage-3 could not run because the 8B daily quota is exhausted. Caller
    should fall back to posting the alert without a suggestion (degraded but
    still useful) — do NOT defer the alert itself."""


def suggest(enriched: EnrichedHit, cls: Classification) -> CommentSuggestion | None:
    """Draft a comment suggestion. Returns None for noise (caller should
    skip), a CommentSuggestion otherwise (possibly with empty
    suggested_comment + skip_reason set when the model declines)."""
    if cls.bucket == "noise":
        return None

    hit = enriched.hit
    user_msg = comment_suggest_user_message(
        title=hit.title,
        body=hit.body,
        comments_snippet=bucket_mod._comments_snippet(enriched),
        bucket=cls.bucket,
        mentioned_competitors=cls.mentioned_competitors,
        buyer_persona_hint=cls.buyer_persona_hint,
        company_size_hint=cls.company_size_hint,
    )
    try:
        resp = groq_quota.chat_complete(
            bucket_mod._get_client(),
            model=_MODEL,
            messages=[
                {"role": "system", "content": COMMENT_SUGGEST_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=400,
            temperature=0.4,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate_limit" in msg.lower():
            raise CommentSuggestRateLimited(msg) from e
        print(f"[comment_suggest] Groq error for {hit.post_id}: {e}")
        return CommentSuggestion(
            post_id=hit.post_id,
            suggested_comment="",
            plug_strategy="skip",
            rationale="",
            skip_reason=f"groq_error: {msg[:120]}",
            prompt_version=COMMENT_PROMPT_VERSION,
        )

    strategy = data.get("plug_strategy", "skip")
    if strategy not in _VALID_STRATEGIES:
        strategy = "skip"
    suggested = (data.get("suggested_comment") or "").strip()
    skip_reason = data.get("skip_reason")
    # Coerce: empty suggestion forces strategy=skip; populated suggestion
    # without strategy gets a sane default.
    if not suggested:
        strategy = "skip"
    elif strategy == "skip":
        # Model returned text but called it skip — trust the strategy and
        # drop the text so we don't render a draft we shouldn't.
        suggested = ""

    return CommentSuggestion(
        post_id=hit.post_id,
        suggested_comment=suggested,
        plug_strategy=strategy,
        rationale=(data.get("rationale") or "").strip(),
        skip_reason=skip_reason,
        prompt_version=COMMENT_PROMPT_VERSION,
    )
