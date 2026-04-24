import time
from datetime import datetime, timezone

import requests

from models import RedditHit

_SUBMISSION_URL = "https://api.pullpush.io/reddit/submission/search/"
_COMMENT_URL = "https://api.pullpush.io/reddit/comment/search/"
_PAGE_SIZE = 100


def _to_hit(item: dict) -> RedditHit | None:
    post_id = item.get("id")
    if not post_id:
        return None
    created = item.get("created_utc")
    if created is None:
        return None
    permalink = item.get("full_link") or item.get("url") or ""
    if permalink and permalink.startswith("/r/"):
        permalink = f"https://www.reddit.com{permalink}"
    return RedditHit(
        post_id=f"t3_{post_id}",
        subreddit=item.get("subreddit", "unknown"),
        author=item.get("author") or None,
        title=item.get("title", "") or "",
        body=item.get("selftext") or None,
        permalink=permalink,
        created_utc=datetime.fromtimestamp(float(created), tz=timezone.utc),
        score=item.get("score"),
        num_comments=item.get("num_comments"),
        source="pullpush",
        matched_keywords=[],
    )


def _paginate(url: str, params: dict) -> list[dict]:
    results: list[dict] = []
    after = params.get("after")
    before = params.get("before")
    working = dict(params)
    working["size"] = _PAGE_SIZE
    while True:
        try:
            resp = requests.get(url, params=working, timeout=60)
            resp.raise_for_status()
            batch = resp.json().get("data") or []
        except Exception as e:
            print(f"[pullpush] error fetching {url}: {e}")
            return results
        if not batch:
            return results
        results.extend(batch)
        earliest = min(item.get("created_utc", 0) for item in batch)
        if after is not None and earliest <= after:
            return results
        working["before"] = int(earliest)
        if before is not None and int(earliest) <= int(before):
            # still moving backward within the window; continue
            pass
        time.sleep(1.0)


def search_submissions(keyword: str, start: datetime, end: datetime) -> list[RedditHit]:
    params = {
        "q": keyword,
        "after": int(start.timestamp()),
        "before": int(end.timestamp()),
        "sort": "desc",
        "sort_type": "created_utc",
    }
    raw = _paginate(_SUBMISSION_URL, params)
    out: list[RedditHit] = []
    for item in raw:
        hit = _to_hit(item)
        if hit is not None:
            hit.matched_keywords = [keyword]
            out.append(hit)
    return out


def search_comments(keyword: str, start: datetime, end: datetime) -> list[dict]:
    """Returns raw comment dicts — caller decides whether to persist as hits."""
    params = {
        "q": keyword,
        "after": int(start.timestamp()),
        "before": int(end.timestamp()),
        "sort": "desc",
        "sort_type": "created_utc",
    }
    return _paginate(_COMMENT_URL, params)
