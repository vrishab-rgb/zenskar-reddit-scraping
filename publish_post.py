"""Deliver a written canonical Reddit post draft to Slack.

Intended to be called by a Cowork scheduled agent right after it writes a post:
the agent writes the draft to a markdown file (with optional front matter), then
runs this to push a formatted version to the Slack review channel. No
intermediate doc + fetch step — the agent writes and delivers in one shot.

Front matter (optional, between --- lines at the top of the file):

    ---
    title: Evaluated 6 billing tools for usage + commit pricing
    subreddit: SaaS
    source_url: https://www.zenskar.com/buyers-guide/usage-based-billing-software
    notes: post from founder account; warm the account first
    ---
    <post body in markdown>

Usage:
    python publish_post.py --file path/to/draft.md
    python publish_post.py --file draft.md --title "..." --subreddit SaaS
"""

import argparse
import sys

from outputs import slack


def _parse_front_matter(text: str) -> tuple[dict, str]:
    """Return (meta, body). Front matter is a simple key: value block fenced by
    --- lines at the very top. Absent -> ({}, whole text)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip().lower()] = v.strip()
    return meta, parts[2].lstrip("\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="markdown draft file (optional front matter)")
    ap.add_argument("--title", help="override/title if not in front matter")
    ap.add_argument("--subreddit", help="override subreddit")
    ap.add_argument("--source-url", help="override source page url")
    ap.add_argument("--notes", help="override notes")
    args = ap.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    with open(args.file, encoding="utf-8") as f:
        meta, body = _parse_front_matter(f.read())

    title = args.title or meta.get("title")
    if not title:
        print("[publish_post] no title (front matter 'title:' or --title required)")
        return 1
    if not body.strip():
        print("[publish_post] empty post body")
        return 1

    used = slack.post_reddit_post_draft(
        title=title,
        body=body,
        subreddit=args.subreddit or meta.get("subreddit"),
        source_url=args.source_url or meta.get("source_url"),
        notes=args.notes or meta.get("notes"),
    )
    if not used:
        print("[publish_post] delivery failed (no webhook or HTTP error)")
        return 1
    print(f"[publish_post] delivered '{title}' to Slack")
    return 0


if __name__ == "__main__":
    sys.exit(main())
