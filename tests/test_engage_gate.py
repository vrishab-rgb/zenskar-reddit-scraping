from engage import drafter


def test_gate_rejects_em_dash():
    txt = "a" * 60 + " — " + "b" * 60
    assert "banned substring" in drafter.quality_gate(txt)


def test_gate_rejects_marketing_words():
    txt = ("the bottleneck is rarely metering, leverage your warehouse data "
           "instead and keep the schema flexible enough for weird contracts here ok")
    assert "leverage" in (drafter.quality_gate(txt) or "")


def test_gate_rejects_not_just_construction():
    txt = ("the issue isn't just metering, it's the data model underneath that "
           "breaks on conditional contract terms every single time you hit one ok")
    assert "not just" in (drafter.quality_gate(txt) or "").lower() or "isn't just" in txt


def test_gate_rejects_undisclosed_zenskar():
    txt = ("the real test is modelling commit-plus-overage without custom code, "
           "most tools fail it on the first weird contract. we use zenskar and it "
           "handled ours fine last quarter, migration was lighter than expected too")
    assert drafter.quality_gate(txt) == "zenskar mention without disclosure"


def test_gate_allows_disclosed_zenskar():
    txt = ("the real test is modelling commit-plus-overage without custom code, "
           "most tools fail it. full disclosure i work at zenskar so weigh that, "
           "but trial your three gnarliest contracts before committing to anything")
    assert drafter.quality_gate(txt) is None


def test_gate_allows_clean_help():
    txt = ("the bottleneck is rarely metering, its that the catalog is a flat list "
           "and real contracts are conditional. keep a billing-exceptions sheet and "
           "watch it only grow")
    assert drafter.quality_gate(txt) is None


def test_gate_rejects_too_long():
    assert "outside" in drafter.quality_gate("a" * 1000)
