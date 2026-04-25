import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from classify import bucket as bucket_mod
from classify import comment_suggest as suggest_mod
from models import Classification, Comment, EnrichedHit, RedditHit


def _enriched(title="Looking for a Chargebee alternative for usage-based billing",
              body="We've outgrown Chargebee for our metered API pricing. Anyone have suggestions?"):
    hit = RedditHit(
        post_id="t3_sugg",
        subreddit="SaaS",
        author="alice",
        title=title,
        body=body,
        permalink="https://reddit.com/r/SaaS/comments/xyz/",
        created_utc=datetime.now(timezone.utc),
        score=15,
        num_comments=4,
        source="rss_search",
        matched_keywords=["Chargebee"],
    )
    return EnrichedHit(
        hit=hit,
        comments=[Comment(author="b", body="We use Stripe Billing now.", score=2)],
    )


def _cls(bucket="lead_signal", competitors=None):
    return Classification(
        post_id="t3_sugg",
        bucket=bucket,
        mentioned_competitors=competitors or ["Chargebee"],
        buyer_persona_hint="Controller",
        company_size_hint="midmarket",
        pain_points=["usage-based billing"],
        sentiment="neu",
    )


def _fake_client(payload: dict | None = None, raise_exc: Exception | None = None):
    parsed = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload or {})))]
    )

    class _Raw:
        headers = {"x-ratelimit-remaining-tokens": "499000"}
        def parse(self):
            if raise_exc is not None:
                raise raise_exc
            return parsed

    class _WithRaw:
        @staticmethod
        def create(**kwargs):
            if raise_exc is not None:
                raise raise_exc
            return _Raw()

    class _C:
        class chat:
            class completions:
                with_raw_response = _WithRaw()
    return _C()


def test_returns_none_for_noise_bucket():
    out = suggest_mod.suggest(_enriched(), _cls(bucket="noise"))
    assert out is None


def test_direct_recommend_for_alternative_seeker(mocker):
    payload = {
        "suggested_comment": "If you've outgrown Chargebee on metered pricing, the issue is usually that linear price catalogs can't model usage tiers cleanly. Worth looking at Zenskar — its graphical pricing model handles hybrid usage+commit contracts without engineering work, and there's no % of revenue. (disclosure: I work at Zenskar)",
        "plug_strategy": "direct_recommend",
        "rationale": "Author explicitly asks for a Chargebee alternative for usage-based billing, which is a direct fit.",
        "skip_reason": None,
    }
    mocker.patch.object(bucket_mod, "_get_client", return_value=_fake_client(payload))
    out = suggest_mod.suggest(_enriched(), _cls())
    assert out is not None
    assert out.plug_strategy == "direct_recommend"
    assert "Zenskar" in out.suggested_comment
    assert out.skip_reason is None
    assert out.post_id == "t3_sugg"


def test_skip_when_model_declines(mocker):
    payload = {
        "suggested_comment": "",
        "plug_strategy": "skip",
        "rationale": "",
        "skip_reason": "post is hostile rant — engagement would be forced",
    }
    mocker.patch.object(bucket_mod, "_get_client", return_value=_fake_client(payload))
    out = suggest_mod.suggest(_enriched(), _cls(bucket="competitor_mention"))
    assert out is not None
    assert out.suggested_comment == ""
    assert out.plug_strategy == "skip"
    assert out.skip_reason


def test_invalid_strategy_coerced_to_skip(mocker):
    payload = {
        "suggested_comment": "Some text",
        "plug_strategy": "made_up_value",
        "rationale": "x",
    }
    mocker.patch.object(bucket_mod, "_get_client", return_value=_fake_client(payload))
    out = suggest_mod.suggest(_enriched(), _cls())
    assert out.plug_strategy == "skip"


def test_strategy_skip_with_text_drops_text(mocker):
    # Defensive: model said skip but also returned text. We shouldn't render
    # a draft we shouldn't, so suggested_comment is cleared.
    payload = {
        "suggested_comment": "I would say something",
        "plug_strategy": "skip",
        "rationale": "x",
        "skip_reason": "off-topic",
    }
    mocker.patch.object(bucket_mod, "_get_client", return_value=_fake_client(payload))
    out = suggest_mod.suggest(_enriched(), _cls())
    assert out.suggested_comment == ""


def test_429_raises_rate_limited(mocker):
    mocker.patch.object(
        bucket_mod, "_get_client",
        return_value=_fake_client(raise_exc=RuntimeError("429 rate_limit_exceeded")),
    )
    with pytest.raises(suggest_mod.CommentSuggestRateLimited):
        suggest_mod.suggest(_enriched(), _cls())


def test_other_groq_error_returns_skip_record(mocker):
    mocker.patch.object(
        bucket_mod, "_get_client",
        return_value=_fake_client(raise_exc=RuntimeError("transient internal error")),
    )
    out = suggest_mod.suggest(_enriched(), _cls())
    assert out is not None
    assert out.plug_strategy == "skip"
    assert out.suggested_comment == ""
    assert out.skip_reason and "groq_error" in out.skip_reason
