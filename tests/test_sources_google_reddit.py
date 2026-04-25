import pytest

from sources import google_reddit


class _Resp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
    def json(self): return self._body
    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"status {self.status_code}")


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "fake-key-for-tests")


def test_no_op_without_api_key(monkeypatch, mocker):
    monkeypatch.delenv("SERPER_API_KEY")
    spy = mocker.patch("sources.google_reddit.requests.post")
    assert google_reddit.fetch_all(["q1", "q2"], max_queries=2) == []
    assert spy.call_count == 0


def test_parses_reddit_url_and_snippet(mocker):
    payload = {"organic": [
        {"title": "Best Chargebee alternatives in 2024",
         "link": "https://www.reddit.com/r/SaaS/comments/abc123/best_chargebee_alts/",
         "snippet": "We left Chargebee for Zenskar. Way better at usage-based pricing."},
        {"title": "Unrelated non-reddit page",
         "link": "https://example.com/blog/post"},
    ]}
    mocker.patch("sources.google_reddit.requests.post", return_value=_Resp(payload))
    hits = google_reddit.search("Chargebee alternative")
    assert len(hits) == 1  # second result skipped — not a reddit URL
    h = hits[0]
    assert h.post_id == "t3_abc123"  # SAME namespace as Reddit RSS → free dedup
    assert h.subreddit == "SaaS"
    assert h.source == "google_reddit"
    assert "Zenskar" in (h.body or "")  # snippet became the body


def test_post_id_collides_with_reddit_rss_for_dedup(mocker):
    """Critical property: a post seen via Google search produces the SAME
    post_id as that post seen via Reddit RSS. So when both sources find it,
    we emit one alert, not two."""
    # Reddit post IDs are lowercase base36 — same shape RSS extracts.
    payload = {"organic": [{
        "title": "x",
        "link": "https://www.reddit.com/r/SaaS/comments/abc123/slug/",
    }]}
    mocker.patch("sources.google_reddit.requests.post", return_value=_Resp(payload))
    h = google_reddit.search("anything")[0]
    assert h.post_id == "t3_abc123"


def test_fetch_all_dedups_and_respects_budget(mocker):
    payload = {"organic": [{
        "title": "x",
        "link": "https://www.reddit.com/r/x/comments/same/slug/",
    }]}
    spy = mocker.patch("sources.google_reddit.requests.post", return_value=_Resp(payload))
    mocker.patch("sources.google_reddit.time.sleep", return_value=None)
    out = google_reddit.fetch_all(["q1", "q2", "q3", "q4"], max_queries=2)
    assert spy.call_count == 2  # budget honored
    assert len(out) == 1  # same post → deduped
    assert sorted(out[0].matched_keywords) == ["q1", "q2"]


def test_swallows_serper_errors(mocker):
    mocker.patch("sources.google_reddit.requests.post",
                 side_effect=RuntimeError("502 bad gateway"))
    assert google_reddit.search("anything") == []
