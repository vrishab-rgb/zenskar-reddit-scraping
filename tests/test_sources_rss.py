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


def test_fetch_feed_backs_off_on_429(mocker):
    class Result:
        def __init__(self, status, entries=None):
            self.status = status
            self.entries = entries or []
            self.bozo = False

    calls = []
    sequence = [Result(429), Result(429), Result(200, entries=["ok"])]

    def fake_parse(url, agent=None):
        calls.append(url)
        return sequence[len(calls) - 1]

    mocker.patch("sources.rss.feedparser.parse", side_effect=fake_parse)
    mocker.patch("sources.rss.time.sleep", return_value=None)
    entries = rss._fetch_feed("https://example.com/feed")
    assert entries == ["ok"]
    assert len(calls) == 3
