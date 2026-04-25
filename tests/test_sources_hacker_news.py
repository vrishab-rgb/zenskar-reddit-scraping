from sources import hacker_news


class _Resp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
    def json(self): return self._body
    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"status {self.status_code}")


def test_story_match_becomes_redditish_hit(mocker):
    payload = {"hits": [{
        "objectID": "42424242",
        "_tags": ["story", "author_alice"],
        "title": "Show HN: alternative to Chargebee for usage-based billing",
        "story_text": "We built this because Chargebee couldn't handle our metered billing.",
        "author": "alice",
        "points": 87,
        "num_comments": 23,
        "created_at_i": 1700000000,
    }]}
    mocker.patch("sources.hacker_news.requests.get", return_value=_Resp(payload))
    hits = hacker_news.fetch_query("Chargebee alternative")
    assert len(hits) == 1
    h = hits[0]
    assert h.post_id == "hn:42424242"
    assert h.subreddit == "Hacker News"
    assert h.source == "hacker_news"
    assert h.author == "alice"
    assert "Chargebee" in h.title
    assert "metered billing" in h.body
    assert h.score == 87
    assert h.matched_keywords == ["Chargebee alternative"]
    assert h.permalink == "https://news.ycombinator.com/item?id=42424242"


def test_comment_match_uses_comment_text_as_title(mocker):
    payload = {"hits": [{
        "objectID": "comment-77",
        "_tags": ["comment"],
        "comment_text": "We left Stripe Billing because it can't model usage tiers cleanly.",
        "author": "bob",
        "created_at_i": 1700000000,
    }]}
    mocker.patch("sources.hacker_news.requests.get", return_value=_Resp(payload))
    hits = hacker_news.fetch_query("Stripe Billing")
    assert len(hits) == 1
    assert hits[0].body is None
    assert "left Stripe Billing" in hits[0].title


def test_dedup_across_queries(mocker):
    # Same objectID returned by two queries → one hit, two matched keywords.
    base = {"objectID": "X", "_tags": ["story"], "title": "t",
            "author": "a", "created_at_i": 1700000000}
    responses = iter([_Resp({"hits": [base]}), _Resp({"hits": [base]})])
    mocker.patch("sources.hacker_news.requests.get", side_effect=lambda *a, **kw: next(responses))
    mocker.patch("sources.hacker_news.time.sleep", return_value=None)
    out = hacker_news.fetch_all(["q1", "q2"], max_queries=2)
    assert len(out) == 1
    assert sorted(out[0].matched_keywords) == ["q1", "q2"]


def test_fetch_query_swallows_http_errors(mocker):
    mocker.patch("sources.hacker_news.requests.get", side_effect=RuntimeError("down"))
    assert hacker_news.fetch_query("anything") == []
