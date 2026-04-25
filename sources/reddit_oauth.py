"""Reddit OAuth token cache (script-app flow).

Why this module exists: as of mid-2023 Reddit aggressively 403s
unauthenticated `.json` calls from datacenter IPs (which is what GitHub
Actions runners are). The fix is to authenticate — Reddit lets script-type
apps trade username+password+client-creds for a bearer token good for ~1
hour, then call oauth.reddit.com instead of www.reddit.com.

Setup (one-time, done by a human via reddit.com/prefs/apps):
- Create a 'script' app — name/description/redirect-uri can be anything.
- Note the 14-char client_id (under the app name) and the 27-char secret.
- Use a Reddit account that owns the app as username/password.

Required env vars: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USERNAME,
REDDIT_PASSWORD. The existing REDDIT_RSS_USER_AGENT is reused as the UA.
"""
import os
import threading
import time

import requests

_TOKEN: str | None = None
_TOKEN_EXPIRES_AT: float = 0.0  # monotonic seconds
_LOCK = threading.Lock()

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_DEFAULT_UA = "zenskar-marketing-monitor/1.0 (contact: priyam.s@zenskar.com)"


class RedditAuthError(RuntimeError):
    pass


def _ua() -> str:
    return os.environ.get("REDDIT_RSS_USER_AGENT") or _DEFAULT_UA


def _fetch_token() -> tuple[str, int]:
    """Exchange username/password + client creds for a bearer token.
    Returns (token, expires_in_seconds). Raises RedditAuthError on any
    missing-env-var or non-200 response."""
    try:
        client_id = os.environ["REDDIT_CLIENT_ID"]
        client_secret = os.environ["REDDIT_CLIENT_SECRET"]
        username = os.environ["REDDIT_USERNAME"]
        password = os.environ["REDDIT_PASSWORD"]
    except KeyError as e:
        raise RedditAuthError(f"missing env var: {e.args[0]}") from e

    resp = requests.post(
        _TOKEN_URL,
        auth=(client_id, client_secret),
        data={"grant_type": "password", "username": username, "password": password},
        headers={"User-Agent": _ua()},
        timeout=15,
    )
    if resp.status_code != 200:
        raise RedditAuthError(f"token endpoint returned {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    token = body.get("access_token")
    if not token:
        raise RedditAuthError(f"token response missing access_token: {body}")
    return token, int(body.get("expires_in", 3600))


def get_token() -> str:
    """Return a valid bearer token, refreshing if expired or near-expiry."""
    global _TOKEN, _TOKEN_EXPIRES_AT
    with _LOCK:
        # 60s safety margin so an in-flight request doesn't race the expiry.
        if _TOKEN and time.monotonic() < _TOKEN_EXPIRES_AT - 60:
            return _TOKEN
        token, expires_in = _fetch_token()
        _TOKEN = token
        _TOKEN_EXPIRES_AT = time.monotonic() + expires_in
        return _TOKEN


def auth_headers() -> dict:
    return {"Authorization": f"Bearer {get_token()}", "User-Agent": _ua()}


def reset_for_tests() -> None:
    """Clear the cached token. Tests use this to avoid leaking state."""
    global _TOKEN, _TOKEN_EXPIRES_AT
    with _LOCK:
        _TOKEN = None
        _TOKEN_EXPIRES_AT = 0.0
