from engage import bofu


def test_competitor_match_returns_facts():
    facts = bofu.grounding_for(["Chargebee"], [], "best chargebee alternative for usage billing")
    assert facts
    assert any("flat-list" in f or "metering" in f for f in facts)


def test_competitor_match_is_precise():
    # Zuora named -> Zuora facts, not Chargebee's.
    facts = bofu.grounding_for(["Zuora"], [], "moving off zuora")
    assert any("6-9" in f for f in facts)
    assert all("chargebee" not in f.lower() for f in facts)


def test_intent_fallback_when_no_competitor():
    facts = bofu.grounding_for([], ["usage-based billing"], "how to pick a metered billing tool")
    assert facts
    assert any("gnarliest" in f or "no-code" in f or "rev rec" in f for f in facts)


def test_no_match_returns_empty():
    assert bofu.grounding_for([], [], "best excel shortcuts for accountants") == []


def test_facts_are_capped():
    facts = bofu.grounding_for(["Chargebee", "Zuora", "Maxio"], ["usage-based billing"], "x")
    assert len(facts) <= 5


def test_competitor_facts_take_precedence_over_intent():
    # When a competitor matches, intent-only entries shouldn't dilute the set.
    facts = bofu.grounding_for(["Chargebee"], ["usage-based billing"], "chargebee alternative")
    # All returned facts should come from the Chargebee entry (competitor match wins).
    chargebee_facts = next(e for e in bofu.CATALOG if e.slug == "alternatives/chargebee").facts
    assert all(f in chargebee_facts for f in facts)
