from datetime import datetime, timezone

import pytest

from models import Classification, CommentSuggestion, EnrichedHit, RedditHit
from outputs import slack


def _enriched(bucket: str, source: str = "rss_sub", subreddit: str = "SaaS") -> tuple[EnrichedHit, Classification]:
    hit = RedditHit(
        post_id="t3_test",
        subreddit=subreddit,
        author="alice",
        title="Chargebee is being weird today",
        body="We noticed webhook retries piling up. Anyone else seeing this?",
        permalink="https://reddit.com/r/SaaS/comments/abc/",
        created_utc=datetime.now(timezone.utc),
        score=5, num_comments=2, source=source,
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
    for v in ["SLACK_WEBHOOK_ALERTS", "SLACK_WEBHOOK_DIGEST", "SLACK_WEBHOOK_HEALTH"]:
        monkeypatch.delenv(v, raising=False)


class _FakeResp:
    status_code = 200
    def raise_for_status(self):
        pass


def test_every_bucket_routes_to_single_alerts_webhook(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    calls = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, **kw: calls.append(url) or _FakeResp())

    for bucket in ("competitor_mention", "lead_signal", "icp_discussion"):
        enriched, cls = _enriched(bucket)
        assert slack.post_alert(enriched, cls) == "#reddit-alerts"
    assert calls == ["https://hooks.example/alerts"] * 3


def test_missing_webhook_skips_cleanly(mocker):
    called = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda *a, **kw: called.append(1) or _FakeResp())
    enriched, cls = _enriched("competitor_mention")
    assert slack.post_alert(enriched, cls) is None
    assert called == []


def test_message_carries_bucket_label_and_link(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
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
    assert "Competitor Mention" in text  # bucket label still visible in single channel


def test_suggestion_block_renders_when_present(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    payloads = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, json=None, **kw: payloads.append(json) or _FakeResp())
    enriched, cls = _enriched("lead_signal")
    sug = CommentSuggestion(
        post_id="t3_test",
        suggested_comment="Worth checking Zenskar — handles usage-based contracts.",
        plug_strategy="direct_recommend",
        rationale="Author asked for an alternative.",
    )
    slack.post_alert(enriched, cls, sug)
    text = payloads[0]["text"]
    assert "Suggested reply" in text
    assert "direct_recommend" in text
    assert "Zenskar" in text
    assert "_Why:_" in text


def test_suggestion_block_omitted_when_skipped(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    payloads = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, json=None, **kw: payloads.append(json) or _FakeResp())
    enriched, cls = _enriched("lead_signal")
    sug = CommentSuggestion(
        post_id="t3_test",
        suggested_comment="",
        plug_strategy="skip",
        rationale="",
        skip_reason="off-topic",
    )
    slack.post_alert(enriched, cls, sug)
    text = payloads[0]["text"]
    assert "Suggested reply" not in text


def test_channel_label_for_reddit(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    payloads = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, json=None, **kw: payloads.append(json) or _FakeResp())
    enriched, cls = _enriched("competitor_mention", source="rss_sub", subreddit="SaaS")
    slack.post_alert(enriched, cls)
    assert "r/SaaS" in payloads[0]["text"]


def test_channel_label_for_hacker_news(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    payloads = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, json=None, **kw: payloads.append(json) or _FakeResp())
    enriched, cls = _enriched("competitor_mention", source="hacker_news", subreddit="Hacker News")
    slack.post_alert(enriched, cls)
    first_line = payloads[0]["text"].splitlines()[0]
    assert "Hacker News" in first_line
    assert "r/Hacker" not in first_line  # don't render as 'r/Hacker News'


def test_channel_label_for_stackoverflow(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    payloads = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, json=None, **kw: payloads.append(json) or _FakeResp())
    enriched, cls = _enriched("competitor_mention", source="stackoverflow", subreddit="so:stripe-billing")
    slack.post_alert(enriched, cls)
    text = payloads[0]["text"]
    assert "Stack Overflow" in text
    assert "stripe-billing" in text


def test_channel_label_for_reddit_comment(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    payloads = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, json=None, **kw: payloads.append(json) or _FakeResp())
    enriched, cls = _enriched("competitor_mention", source="reddit_comments_rss", subreddit="CFO")
    slack.post_alert(enriched, cls)
    assert "r/CFO (comment)" in payloads[0]["text"]


def test_digest_falls_back_to_alerts_webhook(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    calls = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, **kw: calls.append(url) or _FakeResp())
    slack.post_digest("weekly summary")
    assert calls == ["https://hooks.example/alerts"]


def test_digest_prefers_dedicated_webhook_when_set(mocker, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_ALERTS", "https://hooks.example/alerts")
    monkeypatch.setenv("SLACK_WEBHOOK_DIGEST", "https://hooks.example/digest")
    calls = []
    mocker.patch("outputs.slack.requests.post",
                 side_effect=lambda url, **kw: calls.append(url) or _FakeResp())
    slack.post_digest("weekly summary")
    assert calls == ["https://hooks.example/digest"]
