"""Groq rate-limit visibility.

Groq exposes only per-minute (TPM) buckets via response headers — there is
no daily-tokens-remaining header. We have two pieces of state:

1. `_LATEST` — the per-minute remaining/limit/reset fields parsed from the
   most recent response headers, per model.
2. `_USAGE_THIS_RUN` — sum of `usage.total_tokens` from every Groq call we
   make during the current process. Flushed to Supabase at end-of-run via
   `flush_usage_to_db()`. The persisted row in `groq_daily_usage`, plus
   this in-memory delta, gives us a near-live "tokens used today" number.

The daily *limits* aren't published in headers either — Groq exposes them
only in the console. We hardcode the current free-tier values in
`DAILY_LIMITS` below; update them if your plan changes.
"""
import os
from datetime import datetime, timezone

# Free-tier daily token limits (TPD) for the models we use. Confirm at
# https://console.groq.com/settings/limits if you change plans — these
# numbers don't come from any API.
DAILY_LIMITS: dict[str, int] = {
    "llama-3.1-8b-instant": 500_000,
    "openai/gpt-oss-120b": 200_000,
}

_LATEST: dict[str, dict] = {}
_USAGE_THIS_RUN: dict[str, int] = {}
_USED_TODAY_BASELINE: dict[str, int] = {}  # tokens already used today as of run start, per model


def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_float(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    # Groq sends reset values like "1m23s", "12s", "8.421s". Parse the simple
    # forms; fall back to float() for plain numbers.
    try:
        return float(s)
    except ValueError:
        pass
    total = 0.0
    num = ""
    for ch in s:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch == "m" and num:
            total += float(num) * 60
            num = ""
        elif ch == "s" and num:
            total += float(num)
            num = ""
        elif ch == "h" and num:
            total += float(num) * 3600
            num = ""
    return total if total else None


def record(model: str, headers) -> None:
    """Pull rate-limit fields out of a Groq response's headers and stash them.

    `headers` is an httpx.Headers (case-insensitive mapping). We accept any
    Mapping for test convenience.
    """
    try:
        get = headers.get
    except AttributeError:
        return
    _LATEST[model] = {
        "remaining_tokens": _to_int(get("x-ratelimit-remaining-tokens")),
        "remaining_requests": _to_int(get("x-ratelimit-remaining-requests")),
        "reset_tokens_seconds": _to_float(get("x-ratelimit-reset-tokens")),
        "limit_tokens": _to_int(get("x-ratelimit-limit-tokens")),
    }


def snapshot() -> dict[str, dict]:
    return dict(_LATEST)


def usage_this_run() -> dict[str, int]:
    return dict(_USAGE_THIS_RUN)


def seed_baseline_from_db() -> None:
    """Fetch tokens-used-today for each tracked model from Supabase. Called
    once at run start so format_summary can show a near-live "used today"
    number without hitting the DB on every line."""
    # Lazy import — keeps groq_quota importable in tests that don't touch DB.
    import db
    for model in DAILY_LIMITS:
        _USED_TODAY_BASELINE[model] = db.get_groq_tokens_used_today(model)


def flush_usage_to_db() -> None:
    """Persist this run's accumulated usage to Supabase. Idempotent in the
    sense that repeated calls flush only what's been added since the last
    flush — we clear `_USAGE_THIS_RUN` after writing."""
    import db
    for model, used in list(_USAGE_THIS_RUN.items()):
        if used <= 0:
            continue
        db.add_groq_tokens_used(model, used)
        _USED_TODAY_BASELINE[model] = _USED_TODAY_BASELINE.get(model, 0) + used
        _USAGE_THIS_RUN[model] = 0


def _used_today(model: str) -> int:
    """Best estimate of tokens consumed today (UTC) for this model:
    the DB baseline (loaded at run start) plus what we've accumulated in
    memory since then but haven't flushed yet."""
    return _USED_TODAY_BASELINE.get(model, 0) + _USAGE_THIS_RUN.get(model, 0)


def format_summary() -> str:
    """Render a one-line health-feed-friendly summary. Prefers daily numbers
    (used/limit, remaining) since that's what bills/quota actually mean.
    Falls back to per-minute headroom if no daily data has loaded yet."""
    if not DAILY_LIMITS and not _LATEST:
        return "groq_quota=unknown"
    parts = []
    # Daily section — the headline.
    for model, daily_limit in DAILY_LIMITS.items():
        alias = model.split("/")[-1]
        used = _used_today(model)
        remaining = max(daily_limit - used, 0)
        pct = (used / daily_limit * 100) if daily_limit else 0
        parts.append(f"{alias}: {remaining:,}tok left today ({used:,}/{daily_limit:,}, {pct:.1f}% used)")
    # Per-minute section — small, in parens, only if we have data.
    tpm_bits = []
    for model, info in _LATEST.items():
        rt = info.get("remaining_tokens")
        lt = info.get("limit_tokens")
        if rt is None:
            continue
        alias = model.split("/")[-1]
        tpm_bits.append(f"{alias}={rt}/{lt or '?'}tpm")
    suffix = f"  (TPM: {', '.join(tpm_bits)})" if tpm_bits else ""
    return "groq_quota — " + "  |  ".join(parts) + suffix


def chat_complete(client, **kwargs):
    """Wrap client.chat.completions.create so we always capture rate-limit
    headers AND accumulate usage tokens for daily-quota tracking. Returns
    the parsed completion (same shape callers used before).

    Tests can mock at this boundary OR continue mocking _get_client(); the
    fake client just needs to expose chat.completions.with_raw_response.create.
    """
    raw = client.chat.completions.with_raw_response.create(**kwargs)
    model = kwargs.get("model", "unknown")
    headers = getattr(raw, "headers", None)
    if headers is not None:
        record(model, headers)
    parsed = raw.parse()
    usage = getattr(parsed, "usage", None)
    total = getattr(usage, "total_tokens", None) if usage is not None else None
    if isinstance(total, int) and total > 0:
        _USAGE_THIS_RUN[model] = _USAGE_THIS_RUN.get(model, 0) + total
    return parsed


def _probe(model: str) -> None:
    """Issue a 1-token call to populate the snapshot for `model` and print it."""
    from groq import Groq
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    try:
        chat_complete(
            client,
            model=model,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            temperature=0,
        )
    except Exception as e:
        print(f"[groq_quota] probe error for {model}: {e}")


def main() -> int:
    """`python -m classify.groq_quota` — probe both models we use today
    AND show today's daily usage from Supabase."""
    from dotenv import load_dotenv
    load_dotenv()
    seed_baseline_from_db()
    _probe("llama-3.1-8b-instant")
    _probe("openai/gpt-oss-120b")
    flush_usage_to_db()
    print(format_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
