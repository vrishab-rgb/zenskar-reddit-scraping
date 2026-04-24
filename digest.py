import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests

from outputs import digest_renderer, slack

_REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _iso_week_bounds(label: str) -> tuple[datetime, datetime]:
    """Parse 'YYYY-Www' (e.g. '2026-W17'). Return (monday_utc_start, next_monday_utc_start)."""
    year_str, week_str = label.upper().split("-W")
    year, week = int(year_str), int(week_str)
    monday = date.fromisocalendar(year, week, 1)
    start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def _this_week_label() -> str:
    today = datetime.now(timezone.utc).date()
    year, week, _ = today.isocalendar()
    return f"{year}-W{week:02d}"


def _fetch_rows(start: datetime, end: datetime) -> list[dict]:
    url = f"{os.environ['SUPABASE_URL']}/rest/v1/reddit_hits"
    headers = {
        "apikey": os.environ["SUPABASE_KEY"],
        "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}",
    }
    params = {
        "created_utc": [f"gte.{start.isoformat()}", f"lt.{end.isoformat()}"],
        "select": "post_id,subreddit,author,title,permalink,score,num_comments,created_utc",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=60)
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        return []

    ids = ",".join(h["post_id"] for h in hits)
    cls_url = f"{os.environ['SUPABASE_URL']}/rest/v1/reddit_classifications"
    cls_params = {
        "post_id": f"in.({ids})",
        "select": "post_id,bucket,mentioned_competitors,buyer_persona_hint,company_size_hint,pain_points,sentiment",
    }
    resp = requests.get(cls_url, headers=headers, params=cls_params, timeout=60)
    resp.raise_for_status()
    cls_by_id = {c["post_id"]: c for c in resp.json()}

    rows = []
    for h in hits:
        c = cls_by_id.get(h["post_id"])
        if c is None:
            continue
        rows.append({**h, **c})
    return rows


def generate(week_label: str, dry_run: bool = False) -> str:
    start, end = _iso_week_bounds(week_label)
    print(f"[digest] week={week_label} range=[{start.date()}, {end.date()})")
    rows = _fetch_rows(start, end)
    print(f"[digest] rows (classified, non-null): {len(rows)}")
    markdown = digest_renderer.render(rows, week_label)

    if dry_run:
        print("[digest][dry-run] rendered markdown:\n")
        print(markdown)
        return markdown

    os.makedirs(_REPORTS_DIR, exist_ok=True)
    path = os.path.join(_REPORTS_DIR, f"{week_label}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(f"[digest] wrote {path}")

    bucket_counts = {}
    for r in rows:
        b = r.get("bucket", "unknown")
        bucket_counts[b] = bucket_counts.get(b, 0) + 1
    bc_str = ", ".join(f"{k}={v}" for k, v in bucket_counts.items()) or "no classified hits"
    slack.post_digest(f"📬 Weekly Reddit digest — {week_label}\n{bc_str}\nReport: reports/{week_label}.md")
    return markdown


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", default=None, help="ISO week label, e.g. 2026-W17. Defaults to current week.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    generate(args.week or _this_week_label(), dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
