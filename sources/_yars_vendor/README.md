# Vendored YARS

Source copied from https://github.com/datavorous/yars (MIT, see `LICENSE` in
this directory) at commit `ce01ca7` on 2026-04-24.

**Why vendored rather than `pip install`ed:** upstream's `pyproject.toml`
declares the distribution name as `sm`, not `yars`, which modern pip strict-rejects
with `has inconsistent name: expected 'yars', but metadata has 'sm'`. Vendoring
sidesteps the packaging mismatch and removes a git install from CI.

**Import path:** `from sources._yars_vendor.yars import YARS`.

**When to re-sync:** if YARS upstream fixes a Reddit-API-parsing bug we hit,
replace these files from the same GitHub path (the 5 files mirror the
`src/yars/` subdirectory). Keep `LICENSE` alongside.

**Do not edit files in this directory.** If YARS's API breaks our use, fix it
in `sources/yars_enrich.py` instead — that's the adapter layer.
