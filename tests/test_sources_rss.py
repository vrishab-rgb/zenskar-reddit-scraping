import os
from unittest.mock import patch

import feedparser

from sources import rss

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "rss_sample.xml")


def _load_sample() -> list:
    with open(_FIXTURE, "r", encoding="utf-8") as f:
        return feedparser.parse(f.read()).entries


def test_subreddit_fetch_parses_each_entry(mocker):
    mocker.patch.object(rss, "_fetch_feed", return_value=_load_sample())
    hits = rss.fetch_subreddit_new("SaaS")
    assert len(hits) == 3
    by_id = {h.post_id: h for h in hits}
    assert "t3_exactmatch1" in by_id
    assert by_id["t3_exactmatch1"].author == "alice"
    assert by_id["t3_exactmatch1"].subreddit == "SaaS"
    assert by_id["t3_exactmatch1"].source == "rss_sub"
    assert "Chargebee" in by_id["t3_exactmatch1"].title


def test_search_post_filters_loose_matches(mocker):
    mocker.patch.object(rss, "_fetch_feed", return_value=_load_sample())
    hits = rss.fetch_search("Zuora")
    ids = {h.post_id for h in hits}
    assert "t3_exactmatch1" in ids, "exact-match entry should pass"
    assert "t3_loosematch1" not in ids, "tokeniser false-positive ('Zuma') must be dropped"
    assert all(h.source == "rss_search" for h in hits)
    assert all("Zuora" in h.matched_keywords for h in hits)


def test_fetch_all_merges_and_unions_keywords(mocker):
    mocker.patch.object(rss, "_fetch_feed", return_value=_load_sample())
    hits = rss.fetch_all(["SaaS"], ["Zuora", "Chargebee"])
    by_id = {h.post_id: h for h in hits}
    merged = by_id["t3_exactmatch1"]
    # First seen as rss_sub (no matched keywords); later the search path should
    # add both 'Zuora' and 'Chargebee' to matched_keywords.
    assert "Zuora" in merged.matched_keywords
    assert "Chargebee" in merged.matched_keywords


def test_post_id_and_subreddit_helpers():
    link = "https://www.reddit.com/r/SaaS/comments/abc123/some_slug/"
    assert rss._post_id_from_link(link) == "t3_abc123"
    assert rss._subreddit_from_link(link) == "SaaS"
    assert rss._post_id_from_link("not a reddit url") is None


class _FakeResp:
    def __init__(self, status_code=200, text="", content=b""):
        self.status_code = status_code
        self.text = text
        self.content = content or text.encode("utf-8")


def _load_sample_bytes() -> bytes:
    with open(_FIXTURE, "rb") as f:
        return f.read()


def test_fetch_feed_backs_off_on_429(mocker):
    sample = _load_sample_bytes()
    sequence = [
        _FakeResp(status_code=429),
        _FakeResp(status_code=429),
        _FakeResp(status_code=200, content=sample),
    ]
    calls = []

    def fake_get(url, headers=None, timeout=None, allow_redirects=True):
        calls.append(url)
        return sequence[len(calls) - 1]

    mocker.patch("sources.rss.requests.get", side_effect=fake_get)
    mocker.patch("sources.rss.time.sleep", return_value=None)
    entries = rss._fetch_feed("https://example.com/feed")
    assert len(entries) == 3  # fixture has 3 entries
    assert len(calls) == 3


def test_fetch_feed_retries_on_html_interstitial(mocker):
    sample = _load_sample_bytes()
    html = "<!DOCTYPE html>\n<html><body>Please verify you are human</body></html>"
    sequence = [
        _FakeResp(status_code=200, text=html),
        _FakeResp(status_code=200, content=sample),
    ]
    calls = []

    def fake_get(url, headers=None, timeout=None, allow_redirects=True):
        calls.append(url)
        return sequence[len(calls) - 1]

    mocker.patch("sources.rss.requests.get", side_effect=fake_get)
    mocker.patch("sources.rss.time.sleep", return_value=None)
    entries = rss._fetch_feed("https://example.com/feed")
    assert len(entries) == 3
    assert len(calls) == 2


def test_looks_like_html_discriminator():
    assert rss._looks_like_html("<!DOCTYPE html>\n<html>") is True
    assert rss._looks_like_html("  <html lang='en'>") is True
    assert rss._looks_like_html("<?xml version='1.0'?>") is False
    assert rss._looks_like_html("") is False
