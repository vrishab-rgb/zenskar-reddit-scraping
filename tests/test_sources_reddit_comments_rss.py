from types import SimpleNamespace

from sources import reddit_comments_rss


def _entry(link, title="", summary=""):
    return SimpleNamespace(
        link=link, title=title, summary=summary,
        author="/u/alice", updated_parsed=None, published_parsed=None,
    )


def test_comment_id_extraction():
    link = "https://www.reddit.com/r/SaaS/comments/abc123/some_post_slug/def456/"
    assert reddit_comments_rss._comment_id_from_link(link) == "def456"


def test_no_keyword_filter_streams_everything_through(mocker):
    """Comment-RSS no longer pre-filters by keyword — comment bodies
    rarely mention topic-words, so we let stage-1 LLM filter relevance."""
    entries = [
        _entry("https://www.reddit.com/r/SaaS/comments/aaa/slug/c1/",
               title="thoughts on Chargebee?",
               summary="we use Chargebee and it's been pain"),
        _entry("https://www.reddit.com/r/SaaS/comments/bbb/slug/c2/",
               title="random unrelated reply",
               summary="totally unrelated content"),
    ]
    mocker.patch.object(reddit_comments_rss, "_fetch_feed", return_value=entries)
    hits = reddit_comments_rss.fetch_subreddit_comments("SaaS", ["Chargebee", "Zuora"])
    assert len(hits) == 2  # both pass through, regardless of keyword presence
    assert {h.post_id for h in hits} == {"t1_c1", "t1_c2"}
    for h in hits:
        assert h.subreddit == "SaaS"
        assert h.source == "reddit_comments_rss"
        assert h.matched_keywords == []  # no keyword tagging anymore


def test_post_id_collision_safe_with_post_namespace(mocker):
    """A comment's post_id is t1_*, while its parent post's is t3_*. Both can
    coexist in the dedup map without clobbering each other."""
    # Reddit post + comment IDs are lowercase base36 — keep fixture realistic.
    entries = [_entry("https://www.reddit.com/r/x/comments/abc123/slug/c0mm3nt/",
                      title="Chargebee test", summary="")]
    mocker.patch.object(reddit_comments_rss, "_fetch_feed", return_value=entries)
    h = reddit_comments_rss.fetch_subreddit_comments("x", ["Chargebee"])[0]
    assert h.post_id == "t1_c0mm3nt"  # NOT t3_abc123


def test_fetch_all_respects_budget_and_dedups(mocker):
    e1 = _entry("https://www.reddit.com/r/X/comments/p1/slug/c1/",
                title="Chargebee", summary="x")
    e2 = _entry("https://www.reddit.com/r/X/comments/p1/slug/c1/",
                title="Chargebee", summary="x")
    feeds = iter([[e1], [e2]])
    mocker.patch.object(reddit_comments_rss, "_fetch_feed",
                        side_effect=lambda *a, **kw: next(feeds))
    mocker.patch.object(reddit_comments_rss.time, "sleep", return_value=None)
    out = reddit_comments_rss.fetch_all(["X", "Y", "Z"], ["Chargebee"], max_feeds=2)
    # Same comment from both feeds → 1 unique hit
    assert len(out) == 1
