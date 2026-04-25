import pytest

from sources import reddit_oauth


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reddit_oauth.reset_for_tests()
    for k in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET",
             "REDDIT_USERNAME", "REDDIT_PASSWORD"):
        monkeypatch.setenv(k, f"test-{k.lower()}")


class _FakeResp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = str(self._body)
    def json(self):
        return self._body


def test_get_token_caches_and_reuses(mocker):
    captured: list = []
    def fake_post(url, **kw):
        captured.append((url, kw))
        return _FakeResp(200, {"access_token": "abc123", "expires_in": 3600})
    mocker.patch("sources.reddit_oauth.requests.post", side_effect=fake_post)

    t1 = reddit_oauth.get_token()
    t2 = reddit_oauth.get_token()
    assert t1 == "abc123" and t2 == "abc123"
    assert len(captured) == 1  # cached, only one network call
    assert captured[0][0] == reddit_oauth._TOKEN_URL
    # auth headers used HTTP Basic with client creds
    assert captured[0][1]["auth"] == ("test-reddit_client_id", "test-reddit_client_secret")
    assert captured[0][1]["data"]["grant_type"] == "password"


def test_get_token_refreshes_when_near_expiry(mocker):
    bodies = iter([
        {"access_token": "tok-A", "expires_in": 3600},
        {"access_token": "tok-B", "expires_in": 3600},
    ])
    mocker.patch("sources.reddit_oauth.requests.post",
                 side_effect=lambda *a, **kw: _FakeResp(200, next(bodies)))
    # First call: 1 monotonic (to set expires_at). Second call: 2 monotonic
    # (one to check expiry, one to set new expires_at after refresh).
    monot = iter([1000.0, 9_999_999.0, 9_999_999.0])
    mocker.patch("sources.reddit_oauth.time.monotonic",
                 side_effect=lambda: next(monot))
    assert reddit_oauth.get_token() == "tok-A"
    # Second call: monotonic clock has jumped past expiry → refresh.
    assert reddit_oauth.get_token() == "tok-B"


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID")
    with pytest.raises(reddit_oauth.RedditAuthError) as exc:
        reddit_oauth.get_token()
    assert "REDDIT_CLIENT_ID" in str(exc.value)


def test_non_200_raises(mocker):
    mocker.patch("sources.reddit_oauth.requests.post",
                 return_value=_FakeResp(401, {"error": "invalid_grant"}))
    with pytest.raises(reddit_oauth.RedditAuthError) as exc:
        reddit_oauth.get_token()
    assert "401" in str(exc.value)


def test_auth_headers_includes_bearer_and_ua(mocker, monkeypatch):
    monkeypatch.setenv("REDDIT_RSS_USER_AGENT", "ua-for-tests/1.0")
    mocker.patch("sources.reddit_oauth.requests.post",
                 return_value=_FakeResp(200, {"access_token": "xyz", "expires_in": 3600}))
    headers = reddit_oauth.auth_headers()
    assert headers["Authorization"] == "Bearer xyz"
    assert headers["User-Agent"] == "ua-for-tests/1.0"
