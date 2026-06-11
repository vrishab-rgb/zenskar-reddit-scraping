from datetime import datetime, timedelta, timezone

from engage import select


def _recent(hours_ago=2):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _row(post_id, bucket="lead_signal", permalink=None, title="t", created=None,
         subreddit="SaaS", competitors=None):
    pid = post_id
    permalink = permalink or f"https://reddit.com/r/SaaS/comments/{pid.replace('t3_','').replace('t1_','')}/x/"
    return {
        "post_id": pid,
        "subreddit": subreddit,
        "title": title,
        "permalink": permalink,
        "created_utc": created or _recent(),
        "source": "rss_search",
        "reddit_classifications": {
            "bucket": bucket,
            "pain_points": [],
            "mentioned_competitors": competitors or [],
        },
    }


def test_shape_drops_noise_and_non_reddit():
    assert select.shape(_row("t3_a", bucket="noise")) is None
    hn = _row("t3_b")
    hn["permalink"] = "https://news.ycombinator.com/item?id=1"
    assert select.shape(hn) is None


def test_thread_id_collapses_post_and_comment():
    post = _row("t3_abc")
    comment = _row("t1_xyz", permalink="https://reddit.com/r/SaaS/comments/abc/slug/xyz/")
    assert select.thread_id(post["post_id"], post["permalink"]) == "abc"
    assert select.thread_id(comment["post_id"], comment["permalink"]) == "abc"


def test_pick_excludes_engaged_and_drafted():
    rows = [_row("t3_a"), _row("t3_b"), _row("t3_c")]
    out = select.pick(rows, engaged_ids={"t3_a"}, engaged_threads=set(),
                       drafted_ids={"t3_b"}, limit=10)
    assert [c["post_id"] for c in out] == ["t3_c"]


def test_pick_one_per_thread():
    rows = [
        _row("t3_abc"),
        _row("t1_xyz", permalink="https://reddit.com/r/SaaS/comments/abc/slug/xyz/"),
    ]
    out = select.pick(rows, set(), set(), set(), limit=10)
    assert len(out) == 1


def test_pick_orders_by_bucket_priority():
    rows = [
        _row("t3_icp", bucket="icp_discussion", title="icp post"),
        _row("t3_lead", bucket="lead_signal", title="lead post"),
        _row("t3_comp", bucket="competitor_mention", title="comp post"),
    ]
    out = select.pick(rows, set(), set(), set(), limit=10)
    assert [c["post_id"] for c in out] == ["t3_lead", "t3_comp", "t3_icp"]


def test_pick_dedups_crosspost_titles():
    rows = [
        _row("t3_a", title="Same Title Here"),
        _row("t3_b", title="same title here  "),
    ]
    out = select.pick(rows, set(), set(), set(), limit=10)
    assert len(out) == 1


def test_shape_drops_stale_threads():
    assert select.shape(_row("t3_old", created=_recent(hours_ago=72))) is None
    assert select.shape(_row("t3_new", created=_recent(hours_ago=2))) is not None


def test_shape_drops_music_subs():
    assert select.shape(_row("t3_g", subreddit="guitar", title="best tabs for this riff")) is None


def test_shape_drops_tabs_only_without_billing_context():
    # 'Tabs' competitor match, no billing token in title -> guitar/browser tabs.
    assert select.shape(_row("t3_t", title="how do you organize your tabs",
                             competitors=["Tabs"])) is None
    # Same competitor but billing context present -> keep.
    assert select.shape(_row("t3_t2", title="anyone used Tabs for usage billing?",
                             competitors=["Tabs"])) is not None


def test_shape_excludes_stripe_billing_only_competitor():
    # Stripe Billing as the sole competitor in a competitor_mention -> excluded.
    assert select.shape(_row("t3_s", bucket="competitor_mention",
                             competitors=["Stripe Billing"])) is None
    # Stripe Billing alongside another tool -> kept.
    assert select.shape(_row("t3_s2", bucket="competitor_mention",
                             competitors=["Stripe Billing", "Chargebee"])) is not None
    # Stripe Billing mentioned but it's a lead_signal (someone asking) -> kept.
    assert select.shape(_row("t3_s3", bucket="lead_signal",
                             competitors=["Stripe Billing"])) is not None
