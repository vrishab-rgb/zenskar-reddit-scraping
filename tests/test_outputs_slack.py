from datetime import datetime, timezone

import pytest

from models import Classification, EnrichedHit, RedditHit
from outputs import slack


def _enriched(bucket: str) -> tuple[EnrichedHit, Classification]:
    hit = RedditHit(
        post_id="t3_test",
        subreddit="SaaS",
        author="alice",
        title="Chargebee is being weird today",
        body="We noticed webhook retries piling up. Anyone else seeing this?",
        permalink="https://reddit.com/r/SaaS/comments/abc/",
        created_utc=datetime.now(timezone.utc),
        score=5, num_comments=2, source="rss_sub",
    )
    cls = Classification(
        post_id="t3_test",
        bucket=bucket,
        mentioned_competitors=["Chargebee"],
        buyer_persona_hint="Engineer",
        company_size_hint="smb",
        sentiment="neg",
    )
    return EnrichedHit(hit=hit), cls


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for v in [
        "SLACK_WEBHOOK_COMPETITORS", "SLACK_WEBHOOK_LEADS", "SLACK_WEBHOOK_ICP",
        "SLACK_WEBHOOK_DEFAULT", "SLACK_WEBHOOK_HEALTH", "SLACK_WEBHOOK_DIGEST",
    ]:
        monkeypatch.delenv(v, raising=False)


class _FakeResp:
    status_code = 200
    def raise_for_status(self):
        pass


def test_bucket_routes_to_specific_webhook(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_COMPETITORS", "https://hooks.example/comp")
    monkeypatch.setenv("SLACK_WEBHOOK_LEADS", "https://hooks.example/leads")
    calls = []
    mocker.patch("outputs.slack.requests.post", side_effect=lambda url, **kw: calls.append(url) or _FakeResp())

    enriched, cls = _enriched("competitor_mention")
    channel = slack.post_alert(enriched, cls)
    assert channel == "#reddit-competitor-watch"
    assert calls == ["https://hooks.example/comp"]


def test_unknown_bucket_falls_back_to_default(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_DEFAULT", "https://hooks.example/default")
    calls = []
    mocker.patch("outputs.slack.requests.post", side_effect=lambda url, **kw: calls.append(url) or _FakeResp())

    enriched, cls = _enriched("lead_signal")  # no LEADS webhook configured
    channel = slack.post_alert(enriched, cls)
    assert channel == "#reddit-leads"
    assert calls == ["https://hooks.example/default"]


def test_missing_webhook_skips_cleanly(mocker):
    # No env vars set; nothing should be posted.
    called = []
    mocker.patch("outputs.slack.requests.post", side_effect=lambda *a, **kw: called.append(1) or _FakeResp())
    enriched, cls = _enriched("icp_discussion")
    assert slack.post_alert(enriched, cls) is None
    assert called == []


def test_message_contains_title_and_link(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_COMPETITORS", "https://hooks.example/comp")
    payloads = []
    def capture(url, json=None, **kw):
        payloads.append(json)
        return _FakeResp()
    mocker.patch("outputs.slack.requests.post", side_effect=capture)

    enriched, cls = _enriched("competitor_mention")
    slack.post_alert(enriched, cls)
    text = payloads[0]["text"]
    assert "Chargebee is being weird today" in text
    assert "https://reddit.com/r/SaaS/comments/abc/" in text
    assert "Competitor" in text or "competitor" in text.lower()
