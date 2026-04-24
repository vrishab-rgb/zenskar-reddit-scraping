from collections import Counter
from datetime import datetime


def _fmt_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso


def _hit_sort_key(row: dict) -> tuple:
    score = row.get("score") or 0
    comments = row.get("num_comments") or 0
    return (-(score + comments), row.get("created_utc", ""))


def _lead_section(rows: list[dict]) -> list[str]:
    out = ["## Lead signals", ""]
    if not rows:
        out.append("_No lead signals this week._")
        return out
    rows_sorted = sorted(rows, key=lambda r: r.get("created_utc", ""), reverse=True)
    for r in rows_sorted[:15]:
        author = r.get("author") or "anonymous"
        pains = r.get("pain_points") or []
        pains_str = f" — pain points: {', '.join(pains)}" if pains else ""
        out.append(f"- **{r['title']}** (r/{r['subreddit']}, u/{author}, {_fmt_time(r['created_utc'])}){pains_str}")
        out.append(f"  {r['permalink']}")
    return out


def _competitor_section(rows: list[dict]) -> list[str]:
    out = ["## Competitor mentions", ""]
    if not rows:
        out.append("_No competitor mentions this week._")
        return out
    rows_sorted = sorted(rows, key=_hit_sort_key)
    freq: Counter[str] = Counter()
    for r in rows_sorted:
        for c in r.get("mentioned_competitors") or []:
            freq[c] += 1
    if freq:
        top = ", ".join(f"{name} ({count})" for name, count in freq.most_common(10))
        out.append(f"Top mentioned: {top}")
        out.append("")
    for r in rows_sorted[:15]:
        mc = r.get("mentioned_competitors") or []
        mc_str = f" — {', '.join(mc)}" if mc else ""
        out.append(f"- **{r['title']}** (r/{r['subreddit']}){mc_str}")
        out.append(f"  {r['permalink']}")
    return out


def _icp_section(rows: list[dict]) -> list[str]:
    out = ["## ICP discussions", ""]
    if not rows:
        out.append("_No ICP discussions this week._")
        return out
    pain_freq: Counter[str] = Counter()
    for r in rows:
        for p in r.get("pain_points") or []:
            pain_freq[p] += 1
    if pain_freq:
        top = ", ".join(f"{p} ({n})" for p, n in pain_freq.most_common(8))
        out.append(f"Recurring pain points: {top}")
        out.append("")
    rows_sorted = sorted(rows, key=_hit_sort_key)
    for r in rows_sorted[:10]:
        out.append(f"- **{r['title']}** (r/{r['subreddit']})")
        out.append(f"  {r['permalink']}")
    return out


def render(rows: list[dict], week_label: str) -> str:
    """rows: each a dict with keys from reddit_hits joined with reddit_classifications."""
    bybucket: dict[str, list[dict]] = {"competitor_mention": [], "lead_signal": [], "icp_discussion": []}
    for r in rows:
        b = r.get("bucket")
        if b in bybucket:
            bybucket[b].append(r)

    total = sum(len(v) for v in bybucket.values())
    lines = [
        f"# Zenskar Reddit Digest — {week_label}",
        "",
        f"Total classified hits this week (excluding noise): **{total}**",
        f"- Competitor mentions: {len(bybucket['competitor_mention'])}",
        f"- Lead signals: {len(bybucket['lead_signal'])}",
        f"- ICP discussions: {len(bybucket['icp_discussion'])}",
        "",
    ]
    lines.extend(_competitor_section(bybucket["competitor_mention"]))
    lines.append("")
    lines.extend(_lead_section(bybucket["lead_signal"]))
    lines.append("")
    lines.extend(_icp_section(bybucket["icp_discussion"]))
    lines.append("")
    return "\n".join(lines)
