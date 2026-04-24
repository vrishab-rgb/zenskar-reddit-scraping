import os

import requests

from models import Classification, EnrichedHit

_ROUTING = {
    "competitor_mention": ("SLACK_WEBHOOK_COMPETITORS", "#reddit-competitor-watch", "👀"),
    "lead_signal":        ("SLACK_WEBHOOK_LEADS",       "#reddit-leads",            "🎯"),
    "icp_discussion":     ("SLACK_WEBHOOK_ICP",         "#reddit-market-insights",  "📊"),
}


def _route(bucket: str) -> tuple[str | None, str, str]:
    env_var, channel, emoji = _ROUTING.get(bucket, (None, "#reddit-default", "🔔"))
    url = os.environ.get(env_var) if env_var else None
    if not url:
        url = os.environ.get("SLACK_WEBHOOK_DEFAULT") or None
    return url, channel, emoji


def _format(hit, cls: Classification, emoji: str) -> str:
    lines = [f"{emoji} *{cls.bucket.replace('_', ' ').title()}* — r/{hit.subreddit}"]
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


def post_alert(enriched: EnrichedHit, cls: Classification) -> str | None:
    """Post to bucket-specific Slack webhook; return channel name on success, None on skip/error."""
    url, channel, emoji = _route(cls.bucket)
    if not url:
        print(f"[slack] no webhook configured for bucket={cls.bucket}; skipping")
        return None
    payload = {"text": _format(enriched.hit, cls, emoji)}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return channel
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
    url = os.environ.get("SLACK_WEBHOOK_DIGEST") or os.environ.get("SLACK_WEBHOOK_DEFAULT")
    if not url:
        print("[slack] no digest webhook configured; skipping")
        return
    try:
        resp = requests.post(url, json={"text": summary}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"[slack] post_digest error: {e}")
