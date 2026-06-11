"""One-time interactive login to seed the persistent browser profile.

Run this ONCE on the machine that will host the poster:

    python -m engage.seed_login

A real Chromium window opens at old.reddit's login page. Log in by hand
(username/password, plus 2FA if enabled), make sure you land logged in, then
press Enter in the terminal. The session cookies are written to the profile
dir and every future headless poster run reuses them. Re-run only if the
session is ever invalidated (poster reports status 'logged_out').
"""

from engage.poster import _PROFILE_DIR


def main() -> int:
    from playwright.sync_api import sync_playwright

    print(f"[seed_login] using profile dir: {_PROFILE_DIR}")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(_PROFILE_DIR, headless=False)
        page = ctx.new_page()
        page.goto("https://old.reddit.com/login/", wait_until="domcontentloaded")
        print("[seed_login] A browser window is open. Log in to the posting account.")
        input("[seed_login] After you are fully logged in, press Enter here to save the session... ")
        # Re-check on the home page so the saved cookies reflect a logged-in state.
        page.goto("https://old.reddit.com/", wait_until="domcontentloaded")
        logged_in = page.locator("form.logout").count() > 0
        print(f"[seed_login] logged_in={logged_in}")
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
