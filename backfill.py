import argparse
import csv
import os
import re
import sys
from datetime import datetime, timezone

import db
from classify import bucket as bucket_mod
from models import EnrichedHit
from sources import pullpush

_REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def _parse_date(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "backfill"


def run(keyword: str, start: datetime, end: datetime, include_comments: bool,
        do_classify: bool, dry_run: bool) -> None:
    print(f"[backfill] keyword={keyword!r} window=[{start.date()}, {end.date()}]")
    hits = pullpush.search_submissions(keyword, start, end)
    print(f"[backfill] submissions found: {len(hits)}")

    comment_rows: list[dict] = []
    if include_comments:
        comment_rows = pullpush.search_comments(keyword, start, end)
        print(f"[backfill] comments found: {len(comment_rows)}")

    if not dry_run:
        new_count = 0
        for hit in hits:
            if db.is_seen(hit.post_id):
                continue
            db.upsert_hit(hit)
            new_count += 1
            if do_classify:
                cls = bucket_mod.classify(EnrichedHit(hit=hit))
                db.record_classification(cls)
        print(f"[backfill] inserted {new_count} new hits")

    os.makedirs(_REPORTS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    csv_path = os.path.join(_REPORTS_DIR, f"backfill-{_slug(keyword)}-{ts}.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["post_id", "subreddit", "author", "title", "created_utc", "score", "num_comments", "permalink"])
        for h in hits:
            w.writerow([h.post_id, h.subreddit, h.author or "", h.title,
                        h.created_utc.isoformat(), h.score or "", h.num_comments or "", h.permalink])
    print(f"[backfill] wrote {csv_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--include-comments", action="store_true")
    ap.add_argument("--classify", action="store_true", help="Run Groq classification on each hit (default off)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from dotenv import load_dotenv
    load_dotenv()
    run(
        keyword=args.keyword,
        start=_parse_date(args.from_date),
        end=_parse_date(args.to_date),
        include_comments=args.include_comments,
        do_classify=args.classify,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
