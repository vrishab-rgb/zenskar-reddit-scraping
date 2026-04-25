from types import SimpleNamespace

from classify import groq_quota


def _reset_state():
    groq_quota._LATEST.clear()
    groq_quota._USAGE_THIS_RUN.clear()
    groq_quota._USED_TODAY_BASELINE.clear()


def test_record_parses_headers():
    _reset_state()
    groq_quota.record("llama-3.1-8b-instant", {
        "x-ratelimit-remaining-tokens": "5963",
        "x-ratelimit-limit-tokens": "6000",
        "x-ratelimit-reset-tokens": "370ms",
    })
    snap = groq_quota.snapshot()
    assert snap["llama-3.1-8b-instant"]["remaining_tokens"] == 5963
    assert snap["llama-3.1-8b-instant"]["limit_tokens"] == 6000


def test_record_handles_missing_headers_gracefully():
    _reset_state()
    groq_quota.record("some-model", {})
    snap = groq_quota.snapshot()
    assert snap["some-model"]["remaining_tokens"] is None


def test_format_summary_shows_daily_remaining_for_known_models():
    _reset_state()
    # Pretend yesterday's run already burned 100k on the 8B model today.
    groq_quota._USED_TODAY_BASELINE["llama-3.1-8b-instant"] = 100_000
    groq_quota._USAGE_THIS_RUN["llama-3.1-8b-instant"] = 5_000
    summary = groq_quota.format_summary()
    # 500_000 - 105_000 = 395_000 left
    assert "395,000tok left today" in summary
    assert "105,000/500,000" in summary
    assert "llama-3.1-8b-instant" in summary
    assert "gpt-oss-120b" in summary  # Always reports both tracked models


def test_format_summary_includes_tpm_when_headers_present():
    _reset_state()
    groq_quota.record("llama-3.1-8b-instant", {
        "x-ratelimit-remaining-tokens": "5963",
        "x-ratelimit-limit-tokens": "6000",
    })
    summary = groq_quota.format_summary()
    assert "TPM:" in summary
    assert "5963/6000tpm" in summary


def test_chat_complete_accumulates_usage():
    _reset_state()
    parsed = SimpleNamespace(
        usage=SimpleNamespace(total_tokens=137),
        choices=[],
    )

    class _Raw:
        headers = {"x-ratelimit-remaining-tokens": "5800",
                   "x-ratelimit-limit-tokens": "6000"}
        def parse(self):
            return parsed

    class _Client:
        class chat:
            class completions:
                class with_raw_response:
                    @staticmethod
                    def create(**kwargs):
                        return _Raw()

    out = groq_quota.chat_complete(_Client(), model="m1", messages=[])
    assert out is parsed
    assert groq_quota.usage_this_run() == {"m1": 137}
    # Second call accumulates
    groq_quota.chat_complete(_Client(), model="m1", messages=[])
    assert groq_quota.usage_this_run() == {"m1": 274}


def test_chat_complete_handles_missing_usage():
    _reset_state()
    parsed = SimpleNamespace(usage=None, choices=[])

    class _Raw:
        headers = {}
        def parse(self):
            return parsed

    class _Client:
        class chat:
            class completions:
                class with_raw_response:
                    @staticmethod
                    def create(**kwargs):
                        return _Raw()

    groq_quota.chat_complete(_Client(), model="m2", messages=[])
    assert groq_quota.usage_this_run().get("m2", 0) == 0


def test_seed_and_flush_round_trip(mocker):
    _reset_state()
    # Mock db.get_groq_tokens_used_today and db.add_groq_tokens_used so
    # we don't need a real Supabase. Captures the values that flow.
    fake_used = {"llama-3.1-8b-instant": 42_000, "openai/gpt-oss-120b": 7_500}
    added: list[tuple[str, int]] = []
    import db as db_mod
    mocker.patch.object(db_mod, "get_groq_tokens_used_today",
                        side_effect=lambda m: fake_used.get(m, 0))
    mocker.patch.object(db_mod, "add_groq_tokens_used",
                        side_effect=lambda m, n: added.append((m, n)))

    groq_quota.seed_baseline_from_db()
    assert groq_quota._USED_TODAY_BASELINE["llama-3.1-8b-instant"] == 42_000

    groq_quota._USAGE_THIS_RUN["llama-3.1-8b-instant"] = 1_000
    groq_quota._USAGE_THIS_RUN["openai/gpt-oss-120b"] = 0  # nothing this run
    groq_quota.flush_usage_to_db()

    assert added == [("llama-3.1-8b-instant", 1_000)]
    # Baseline updated, run counter reset.
    assert groq_quota._USED_TODAY_BASELINE["llama-3.1-8b-instant"] == 43_000
    assert groq_quota._USAGE_THIS_RUN["llama-3.1-8b-instant"] == 0
