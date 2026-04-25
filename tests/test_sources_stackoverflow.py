from sources import stackoverflow


class _Resp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
    def json(self): return self._body
    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"status {self.status_code}")


def test_question_to_hit_basic(mocker):
    payload = {"items": [{
        "question_id": 999,
        "title": "How do I model usage-based billing in Stripe?",
        "owner": {"display_name": "alice"},
        "creation_date": 1700000000,
        "score": 5,
        "answer_count": 3,
        "link": "https://stackoverflow.com/questions/999/how-do-i-model",
    }]}
    mocker.patch("sources.stackoverflow.requests.get", return_value=_Resp(payload))
    hits = stackoverflow.fetch_tag("stripe-billing")
    assert len(hits) == 1
    h = hits[0]
    assert h.post_id == "so:999"
    assert h.subreddit == "so:stripe-billing"
    assert h.source == "stackoverflow"
    assert h.author == "alice"
    assert h.score == 5


def test_dedup_same_question_across_tags(mocker):
    base_q = {"question_id": 555, "title": "tagged twice",
              "creation_date": 1700000000}
    mocker.patch("sources.stackoverflow.requests.get",
                 return_value=_Resp({"items": [base_q]}))
    mocker.patch("sources.stackoverflow.time.sleep", return_value=None)
    out = stackoverflow.fetch_all(max_queries=2)
    # First two tags both return the same question → one hit, multiple kw
    assert len(out) == 1
    assert len(out[0].matched_keywords) == 2


def test_fetch_tag_handles_failure(mocker):
    mocker.patch("sources.stackoverflow.requests.get",
                 side_effect=RuntimeError("offline"))
    assert stackoverflow.fetch_tag("billing") == []
