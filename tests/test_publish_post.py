from publish_post import _parse_front_matter


def test_front_matter_parsed():
    text = "---\ntitle: My Post\nsubreddit: SaaS\n---\nbody here\nsecond line"
    meta, body = _parse_front_matter(text)
    assert meta == {"title": "My Post", "subreddit": "SaaS"}
    assert body == "body here\nsecond line"


def test_no_front_matter_returns_whole_text():
    text = "just a body, no front matter"
    meta, body = _parse_front_matter(text)
    assert meta == {}
    assert body == text


def test_incomplete_front_matter_is_not_parsed():
    text = "---\ntitle: oops never closed\nbody"
    meta, body = _parse_front_matter(text)
    assert meta == {}
    assert body == text


def test_colon_in_value_preserved():
    text = "---\nsource_url: https://x.com/y\n---\nbody"
    meta, body = _parse_front_matter(text)
    assert meta["source_url"] == "https://x.com/y"
