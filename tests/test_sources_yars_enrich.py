import json
import os
from datetime import datetime, timezone

import pytest

from models import RedditHit
from sources import yars_enrich

_FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name):
    with open(os.path.join(_FIX, name), "r", encoding="utf-8") as f:
        return json.load(f)


def _sample_hit() -> RedditHit:
    return RedditHit(
        post_id="t3_abc123",
        subreddit="SaaS",
        author="carol",
        title="Evaluating Chargebee vs Zuora",
        body=None,
        permalink="https://www.reddit.com/r/SaaS/comments/abc123/evaluating_chargebee_vs_zuora/",
        created_utc=datetime.now(timezone.utc),
        score=None,
        num_comments=None,
        source="rss_sub",
    )


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch):
    monkeypatch.setattr(yars_enrich, "_yars_client", None, raising=False)
    monkeypatch.setattr(yars_enrich, "_last_call_at", 0.0, raising=False)


def test_rate_limiter_enforces_spacing(mocker, monkeypatch):
    # Pre-seed "last call" as if we just called YARS at t=100.0, then simulate
    # the next call arriving 2.0s later — which is well under the 6s floor,
    # so _throttle must sleep for 4.0s to pace us.
    monkeypatch.setattr(yars_enrich, "_last_call_at", 100.0, raising=False)
    times = iter([102.0, 106.0])  # (a) check wait, (b) update _last_call_at
    mocker.patch("sources.yars_enrich.time.monotonic", side_effect=lambda: next(times))
    sleeps = []
    mocker.patch("sources.yars_enrich.time.sleep", side_effect=sleeps.append)
    yars_enrich._throttle()
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(yars_enrich.YARS_MIN_INTERVAL_SECONDS - 2.0, abs=0.01)


def test_rate_limiter_skips_sleep_when_already_past_interval(mocker, monkeypatch):
    monkeypatch.setattr(yars_enrich, "_last_call_at", 100.0, raising=False)
    times = iter([200.0, 200.0])
    mocker.patch("sources.yars_enrich.time.monotonic", side_effect=lambda: next(times))
    sleeps = []
    mocker.patch("sources.yars_enrich.time.sleep", side_effect=sleeps.append)
    yars_enrich._throttle()
    assert sleeps == []


def test_fetch_post_failure_returns_none(mocker):
    class BadClient:
        def scrape_post_details(self, permalink):
            raise RuntimeError("cloudflare")
    mocker.patch.object(yars_enrich, "_get_client", return_value=BadClient())
    mocker.patch.object(yars_enrich, "_throttle", return_value=None)
    assert yars_enrich.fetch_post("/r/x/comments/y/") is None


def test_enrich_graceful_fallback_when_yars_fails(mocker):
    mocker.patch.object(yars_enrich, "fetch_post", return_value=None)
    mocker.patch.object(yars_enrich, "fetch_user_hints", return_value=None)
    result = yars_enrich.enrich(_sample_hit())
    assert result.enrichment_failed is True
    assert result.comments == []


def test_enrich_happy_path(mocker):
    post_fixture = _load("yars_post_sample.json")
    user_fixture = _load("yars_user_sample.json")

    class FakeClient:
        def scrape_post_details(self, permalink):
            return post_fixture

        def scrape_user_data(self, username, limit=50):
            return user_fixture

    mocker.patch.object(yars_enrich, "_get_client", return_value=FakeClient())
    mocker.patch.object(yars_enrich, "_throttle", return_value=None)
    mocker.patch.object(yars_enrich, "_fetch_about", return_value={
        "created_utc": 1500000000.0,
        "total_karma": 12345,
    })
    mocker.patch("sources.yars_enrich.db.get_user_hints", return_value=None)
    mocker.patch("sources.yars_enrich.db.upsert_user_hints", return_value=None)

    enriched = yars_enrich.enrich(_sample_hit())

    assert enriched.enrichment_failed is False
    assert len(enriched.comments) == 3
    assert enriched.comments[0].author == "finance_lead"
    assert enriched.hit.body and "mid-market SaaS" in enriched.hit.body

    hints = enriched.user_hints
    assert hints is not None
    assert hints.total_karma == 12345
    assert hints.account_age_days is not None and hints.account_age_days > 0
    assert hints.is_icp_likely is True  # r/accounting, r/CFO, r/FPandA present
    assert "Chargebee" in hints.prior_competitor_mentions
    assert "Zuora" in hints.prior_competitor_mentions


def test_user_hints_uses_cache(mocker):
    cached = mocker.Mock()
    mocker.patch("sources.yars_enrich.db.get_user_hints", return_value=cached)
    result = yars_enrich.fetch_user_hints("carol")
    assert result is cached


def test_permalink_path_accepts_full_url_or_path():
    assert yars_enrich._permalink_path("https://www.reddit.com/r/x/comments/y/z/") == "/r/x/comments/y/z/"
    assert yars_enrich._permalink_path("/r/x/comments/y/z/") == "/r/x/comments/y/z/"
