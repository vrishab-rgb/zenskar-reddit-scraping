from sources import stackoverflow


class _Resp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
    def json(self): return self._body
    def raise_for_status(self):
        if self.status_code != 200:
            raise RuntimeError(f"status {self.status_code}")


def test_buyer_intent_question_passes_filter(mocker):
    payload = {"items": [{
        "question_id": 999,
        "title": "Stripe Billing alternatives for usage-based pricing",
        "owner": {"display_name": "alice"},
        "creation_date": 1700000000,
        "score": 5,
        "answer_count": 3,
        "link": "https://stackoverflow.com/questions/999/best-alternative",
    }]}
    mocker.patch("sources.stackoverflow.requests.get", return_value=_Resp(payload))
    hits = stackoverflow.fetch_tag("stripe-billing")
    assert len(hits) == 1
    h = hits[0]
    assert h.post_id == "so:999"
    assert h.subreddit == "so:stripe-billing"
    assert h.source == "stackoverflow"


def test_routine_integration_question_filtered_out(mocker):
    """Most SO questions are 'how do I do X' — those flooded alerts in
    the previous run. Pre-filter at the source layer so they never reach
    stage-1."""
    payload = {"items": [{
        "question_id": 1001,
        "title": "How do I implement a Chargebee webhook in Node.js?",
        "creation_date": 1700000000,
    }]}
    mocker.patch("sources.stackoverflow.requests.get", return_value=_Resp(payload))
    assert stackoverflow.fetch_tag("chargebee") == []


def test_buyer_intent_regex_examples():
    yes = [
        "Chargebee alternatives for SaaS",
        "Zuora vs Stripe Billing for B2B",
        "Migrating from Recurly to something else",
        "Best billing platform for usage-based pricing",
        "Compared Maxio and SaaSOptics — anyone have experience?",
        "Switching from Chargebee, recommendations?",
    ]
    no = [
        "How do I add a webhook in Chargebee?",
        "Stripe Billing API returns 500",
        "Zuora REST API: how to update subscription",
        "Recurly callback signature validation",
    ]
    for t in yes:
        assert stackoverflow._has_buyer_intent(t), f"should match: {t}"
    for t in no:
        assert not stackoverflow._has_buyer_intent(t), f"should NOT match: {t}"


def test_dedup_same_question_across_tags(mocker):
    # Title must contain buyer-intent terminology now, otherwise the
    # source filter drops it.
    base_q = {"question_id": 555, "title": "Best billing platform for SaaS",
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
