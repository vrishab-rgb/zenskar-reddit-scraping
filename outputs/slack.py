import os

import requests

from models import Classification, CommentSuggestion, EnrichedHit

_BUCKET_DECORATION = {
    "competitor_mention": ("Competitor Mention", "👀"),
    "lead_signal":        ("Lead Signal",        "🎯"),
    "icp_discussion":     ("ICP Discussion",     "📊"),
}

_ALERT_CHANNEL = "#reddit-alerts"


def _get_alert_url() -> str | None:
    return os.environ.get("SLACK_WEBHOOK_ALERTS") or None


def _decoration(bucket: str) -> tuple[str, str]:
    return _BUCKET_DECORATION.get(bucket, (bucket.replace("_", " ").title(), "🔔"))


def _format_suggestion(s: CommentSuggestion) -> str | None:
    """Render the suggestion block, or None when there's nothing useful to show."""
    if not s.suggested_comment.strip():
        return None
    quoted = "\n".join(f"> {line}" for line in s.suggested_comment.splitlines())
    lines = [f"💬 *Suggested reply* (plug: {s.plug_strategy})", quoted]
    if s.rationale:
        lines.append(f"_Why:_ {s.rationale}")
    return "\n".join(lines)


def _format(hit, cls: Classification, label: str, emoji: str) -> str:
    lines = [f"{emoji} *{label}* — r/{hit.subreddit}"]
    lines.append(f"*{hit.title}*")
    if hit.author:
        lines.append(f"by u/{hit.author}")
    snippet = (hit.body or "").strip().replace("\n", " ")[:300]
    if snippet:
        lines.append(f"> {snippet}")
    lines.append(f"<{hit.permalink}|Open post>")
    meta = []
    if cls.mentioned_competitors:
        meta.append(f"Competitors: {', '.join(cls.mentioned_competitors)}")
    if cls.buyer_persona_hint and cls.buyer_persona_hint != "unknown":
        meta.append(f"Persona: {cls.buyer_persona_hint}")
    if cls.company_size_hint and cls.company_size_hint != "unknown":
        meta.append(f"Size: {cls.company_size_hint}")
    if cls.sentiment:
        meta.append(f"Sentiment: {cls.sentiment}")
    if meta:
        lines.append(" · ".join(meta))
    return "\n".join(lines)


def post_alert(
    enriched: EnrichedHit,
    cls: Classification,
    suggestion: CommentSuggestion | None = None,
) -> str | None:
    """Post every non-noise alert to the single alerts webhook. The bucket
    label + emoji in the message header lets readers still scan by category.
    Returns the channel name on success, None on skip/error.

    `suggestion` is optional: if present and non-empty, a 💬 block is appended.
    """
    url = _get_alert_url()
    if not url:
        print(f"[slack] SLACK_WEBHOOK_ALERTS not set; skipping alert for {enriched.hit.post_id}")
        return None
    label, emoji = _decoration(cls.bucket)
    text = _format(enriched.hit, cls, label, emoji)
    if suggestion is not None:
        block = _format_suggestion(suggestion)
        if block:
            text = f"{text}\n\n{block}"
    payload = {"text": text}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return _ALERT_CHANNEL
    except Exception as e:
        print(f"[slack] post_alert error for {enriched.hit.post_id}: {e}")
        return None


def post_health(summary: str) -> None:
    url = os.environ.get("SLACK_WEBHOOK_HEALTH")
    if not url:
        return
    try:
        resp = requests.post(url, json={"text": f"🩺 Reddit monitor\n{summary}"}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[slack] post_health error: {e}")


def post_digest(summary: str) -> None:
    url = os.environ.get("SLACK_WEBHOOK_DIGEST") or _get_alert_url()
    if not url:
        print("[slack] no digest or alerts webhook configured; skipping")
        return
    try:
        resp = requests.post(url, json={"text": summary}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[slack] post_digest error: {e}")
