"""Deterministic Reddit poster driving old.reddit.com via Playwright.

WHY old.reddit + a hardcoded script (not an agent, not new reddit):
new reddit (www) buries the composer in shadow-DOM web components that
selector-based tools can't reach reliably, and an LLM re-reading the DOM each
run is non-deterministic. old.reddit is plain server-rendered HTML: the
comment box is a real <textarea name="text"> with stable selectors that never
change. So posting is a fixed sequence, not a fresh navigation problem.

SESSION: a persistent browser profile (user_data_dir) holds the login cookies.
Seed it ONCE, interactively, with seed_login.py; every run after reuses it.
GitHub Actions can't run this (fresh sandbox, no session) — it runs on a
machine where you've logged in, e.g. a local Windows Task Scheduler job.

DOUBLE-POST SAFETY: the caller flips the draft to 'posting' BEFORE calling
post_comment and never auto-retries a draft left in 'posting' or 'needs_check'.
This module's job is to submit once and report truthfully what happened.
"""

import os
import re
import time
from dataclasses import dataclass
from urllib.parse import urlparse

# Playwright is imported lazily so the rest of the package (drafter, selection,
# db) stays importable in CI where the browser isn't installed.

_PROFILE_DIR = os.environ.get(
    "REDDIT_PROFILE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".reddit-profile"),
)
_NAV_TIMEOUT = 30_000
_EL_TIMEOUT = 15_000
_VERIFY_TIMEOUT = 20_000


@dataclass
class PostResult:
    status: str            # 'posted' | 'needs_check' | 'failed' | 'logged_out'
    comment_url: str = ""
    detail: str = ""


def _old_url(permalink: str) -> str:
    """Normalize any reddit permalink to an old.reddit URL, comments view."""
    parsed = urlparse(permalink)
    path = parsed.path if parsed.netloc else permalink
    return f"https://old.reddit.com{path.rstrip('/')}/"


def _snippet(text: str) -> str:
    """A distinctive slice of our comment to locate it after submit. Reddit
    collapses internal whitespace in rendered markdown, so match on a
    whitespace-normalized prefix."""
    norm = re.sub(r"\s+", " ", text.strip())
    return norm[:60]


def _looks_logged_in(page) -> bool:
    """old.reddit shows a 'login or register' link in the header only when
    logged out, and a user dropdown when logged in."""
    try:
        return page.locator("span.user a.login-required").count() == 0 and (
            page.locator("form.logout").count() > 0
            or page.locator("span.user a[href*='/user/']").count() > 0
        )
    except Exception:
        return False


def _find_top_level_box(page):
    """The post's top-level comment form is the first VISIBLE
    textarea[name=text] in the comment area. Reply forms exist in the DOM too
    but stay hidden until their reply button is clicked, so a visibility
    filter isolates the top-level box deterministically."""
    boxes = page.locator(".commentarea textarea[name='text']")
    count = boxes.count()
    for i in range(count):
        b = boxes.nth(i)
        if b.is_visible():
            return b
    return None


def _open_reply_box(page, comment_id: str):
    """For a comment-reply, click that comment's Reply button to reveal its
    inline composer, then return the textarea scoped to that comment's
    container so we can never reply to the wrong one."""
    cid = comment_id[3:] if comment_id.startswith("t1_") else comment_id
    thing = page.locator(f"div.thing[data-fullname='t1_{cid}']").first
    if thing.count() == 0:
        return None
    # The reply button can read 'reply' or 'reply to comment'; scope to this thing.
    reply_btn = thing.locator("ul.flat-list li a", has_text=re.compile("^reply", re.I)).first
    if reply_btn.count() == 0:
        return None
    reply_btn.click()
    box = thing.locator("textarea[name='text']").first
    box.wait_for(state="visible", timeout=_EL_TIMEOUT)
    return box


def _submit(box):
    """Click the submit button belonging to the same form as `box`. Scoping to
    the enclosing form prevents hitting a different comment's save button."""
    form = box.locator("xpath=ancestor::form[1]")
    btn = form.locator("button[type='submit']").first
    btn.click()


def _capture_permalink(page, snippet: str) -> str:
    """After an AJAX submit old.reddit inserts the new comment into the DOM.
    Find the comment whose body starts with our snippet and read its
    permalink. Returns '' if not found within the timeout (caller -> needs_check)."""
    deadline = time.time() + _VERIFY_TIMEOUT / 1000
    while time.time() < deadline:
        things = page.locator("div.commentarea div.thing.comment")
        for i in range(min(things.count(), 40)):
            thing = things.nth(i)
            body = thing.locator(".usertext-body .md").first
            try:
                txt = re.sub(r"\s+", " ", (body.inner_text() or "").strip())
            except Exception:
                continue
            if txt.startswith(snippet[:40]):
                link = thing.locator("a.bylink").first
                if link.count():
                    href = link.get_attribute("href") or ""
                    if href:
                        return href if href.startswith("http") else f"https://old.reddit.com{href}"
                fullname = thing.get_attribute("data-permalink") or ""
                if fullname:
                    return f"https://old.reddit.com{fullname}"
        page.wait_for_timeout(1000)
    return ""


def post_comment(permalink: str, kind: str, post_id: str, text: str) -> PostResult:
    """Submit ONE comment and report what happened. Never retries internally."""
    from playwright.sync_api import TimeoutError as PWTimeout, sync_playwright

    snippet = _snippet(text)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            _PROFILE_DIR,
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.new_page()
            page.set_default_timeout(_EL_TIMEOUT)
            page.goto(_old_url(permalink), timeout=_NAV_TIMEOUT, wait_until="domcontentloaded")

            if not _looks_logged_in(page):
                return PostResult("logged_out", detail="profile session not logged in; re-run seed_login.py")

            if kind == "comment":
                box = _open_reply_box(page, post_id)
                if box is None:
                    return PostResult("failed", detail=f"target comment {post_id} not found on page")
            else:
                box = _find_top_level_box(page)
                if box is None:
                    return PostResult("failed", detail="top-level comment box not found (locked/archived?)")

            box.scroll_into_view_if_needed()
            box.fill(text)               # fill(), not type() — sets value atomically on a real textarea
            _submit(box)

            url = _capture_permalink(page, snippet)
            if url:
                return PostResult("posted", comment_url=url)
            # Submitted but couldn't confirm — a human checks; we never re-submit.
            return PostResult("needs_check", detail="submit clicked but comment not verified on page")
        except PWTimeout as e:
            return PostResult("needs_check", detail=f"timeout: {e}")
        except Exception as e:
            return PostResult("failed", detail=f"{type(e).__name__}: {e}")
        finally:
            ctx.close()
