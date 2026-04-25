import json
from datetime import datetime, timezone
from types import SimpleNamespace

from classify import bucket as bucket_mod
from models import Comment, EnrichedHit, RedditHit, UserHints


def _enriched(body: str = "We're choosing between Chargebee and Zuora") -> EnrichedHit:
    hit = RedditHit(
        post_id="t3_test",
        subreddit="SaaS",
        author="carol",
        title="Chargebee vs Zuora for mid-market B2B",
        body=body,
        permalink="https://reddit.com/r/SaaS/comments/abc/",
        created_utc=datetime.now(timezone.utc),
        score=10,
        num_comments=3,
        source="rss_search",
        matched_keywords=["Chargebee", "Zuora"],
    )
    return EnrichedHit(
        hit=hit,
        comments=[Comment(author="finance_lead", body="We use Zuora.", score=5)],
        user_hints=UserHints(
            username="carol",
            recent_subreddits=["accounting", "CFO"],
            account_age_days=900,
            total_karma=15000,
            prior_competitor_mentions=["Chargebee"],
            is_icp_likely=True,
        ),
    )


def _fake_groq_response(payload: dict):
    message = SimpleNamespace(content=json.dumps(payload))
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice])


def _fake_client(payload: dict | None = None, raise_exc: Exception | None = None):
    """Build a fake Groq client whose with_raw_response.create returns a
    .parse() callable + a headers mapping — matching the SDK shape we use."""
    parsed = _fake_groq_response(payload or {})
    headers = {"x-ratelimit-remaining-tokens": "199000",
               "x-ratelimit-limit-tokens": "200000",
               "x-ratelimit-reset-tokens": "8000s"}

    class _RawResp:
        def __init__(self):
            self.headers = headers
        def parse(self):
            if raise_exc is not None:
                raise raise_exc
            return parsed

    class _WithRaw:
        @staticmethod
        def create(**kwargs):
            if raise_exc is not None:
                raise raise_exc
            return _RawResp()

    class _Completions:
        with_raw_response = _WithRaw()

    class _Chat:
        completions = _Completions()

    class FakeClient:
        chat = _Chat()
    return FakeClient()


def test_classify_parses_valid_json(mocker):
    payload = {
        "bucket": "competitor_mention",
        "mentioned_competitors": ["Chargebee", "Zuora"],
        "buyer_persona_hint": "Controller",
        "company_size_hint": "midmarket",
        "pain_points": ["usage-based rev rec"],
        "sentiment": "neu",
    }
    mocker.patch.object(bucket_mod, "_get_client", return_value=_fake_client(payload))

    cls = bucket_mod.classify(_enriched())
    assert cls.bucket == "competitor_mention"
    assert cls.mentioned_competitors == ["Chargebee", "Zuora"]
    assert cls.buyer_persona_hint == "Controller"
    assert cls.company_size_hint == "midmarket"
    assert cls.pain_points == ["usage-based rev rec"]
    assert cls.sentiment == "neu"
    assert cls.post_id == "t3_test"


def test_classify_invalid_bucket_coerced_to_noise(mocker):
    payload = {"bucket": "totally_made_up"}
    mocker.patch.object(bucket_mod, "_get_client", return_value=_fake_client(payload))
    cls = bucket_mod.classify(_enriched())
    assert cls.bucket == "noise"


def test_classify_groq_error_returns_noise(mocker):
    mocker.patch.object(
        bucket_mod, "_get_client",
        return_value=_fake_client(raise_exc=RuntimeError("internal error")),
    )
    cls = bucket_mod.classify(_enriched())
    assert cls.bucket == "noise"
    assert cls.post_id == "t3_test"


def test_classify_429_raises_rate_limited(mocker):
    mocker.patch.object(
        bucket_mod, "_get_client",
        return_value=_fake_client(raise_exc=RuntimeError("429 rate_limit_exceeded")),
    )
    import pytest
    with pytest.raises(bucket_mod.BucketRateLimited):
        bucket_mod.classify(_enriched())
