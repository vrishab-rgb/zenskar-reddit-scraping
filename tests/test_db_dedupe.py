from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import db
from models import UserHints


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")
    monkeypatch.setattr(db, "_session", None, raising=False)


class _FakeResp:
    def __init__(self, data=None, status_code=200):
        self._data = data if data is not None else []
        self.status_code = status_code

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def test_is_seen_true(mocker):
    session = SimpleNamespace(
        get=lambda *a, **kw: _FakeResp([{"post_id": "t3_x"}]),
        headers={},
    )
    mocker.patch.object(db, "_get_session", return_value=session)
    assert db.is_seen("t3_x") is True


def test_is_seen_false(mocker):
    session = SimpleNamespace(
        get=lambda *a, **kw: _FakeResp([]),
        headers={},
    )
    mocker.patch.object(db, "_get_session", return_value=session)
    assert db.is_seen("t3_missing") is False


def test_is_seen_network_error_fails_open(mocker):
    def boom(*a, **kw):
        raise RuntimeError("network")
    session = SimpleNamespace(get=boom, headers={})
    mocker.patch.object(db, "_get_session", return_value=session)
    # Returning False on error is the right failure mode: we'd rather re-process
    # than silently skip a new post forever.
    assert db.is_seen("t3_x") is False


def test_get_user_hints_respects_ttl_fresh(mocker):
    fresh = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    session = SimpleNamespace(
        get=lambda *a, **kw: _FakeResp([{
            "username": "alice",
            "fetched_at": fresh,
            "recent_subreddits": ["SaaS", "accounting"],
            "account_age_days": 700,
            "total_karma": 500,
            "prior_competitor_mentions": ["Chargebee"],
            "is_icp_likely": True,
        }]),
        headers={},
    )
    mocker.patch.object(db, "_get_session", return_value=session)
    hints = db.get_user_hints("alice")
    assert hints is not None
    assert hints.username == "alice"
    assert hints.is_icp_likely is True


def test_get_user_hints_returns_none_when_stale(mocker):
    stale = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    session = SimpleNamespace(
        get=lambda *a, **kw: _FakeResp([{
            "username": "alice",
            "fetched_at": stale,
            "recent_subreddits": [],
            "account_age_days": None,
            "total_karma": None,
            "prior_competitor_mentions": [],
            "is_icp_likely": False,
        }]),
        headers={},
    )
    mocker.patch.object(db, "_get_session", return_value=session)
    assert db.get_user_hints("alice") is None


def test_upsert_user_hints_sets_upsert_header(mocker):
    captured = {}
    def post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers or {}
        return _FakeResp()

    session = SimpleNamespace(post=post, headers={})
    mocker.patch.object(db, "_get_session", return_value=session)

    db.upsert_user_hints(UserHints(
        username="alice",
        recent_subreddits=["SaaS"],
        account_age_days=10,
        total_karma=0,
        prior_competitor_mentions=[],
        is_icp_likely=False,
    ))
    assert "reddit_user_hints" in captured["url"]
    assert "resolution=merge-duplicates" in captured["headers"].get("Prefer", "")
    assert captured["json"]["username"] == "alice"
