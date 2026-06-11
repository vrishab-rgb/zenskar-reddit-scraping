"""Gemini Flash comment drafter with a deterministic quality gate.

The previous drafting attempt (Groq 8B, classify/comment_suggest.py) was
removed because weak-model drafts fabricated capabilities. Two defenses here:
the prompt carries the full IS/IS-NOT boundary, and every draft passes a
regex gate for the AI tells that get accounts screenshotted. Gate failures
are recorded as 'rejected' so the candidate isn't re-drafted every run.
"""

import json
import os
import re
from dataclasses import dataclass

from engage import bofu
from engage.prompts import AI_TELL_BANS, DRAFT_PROMPT_VERSION, DRAFT_SYSTEM, draft_user_message

# Floor is deliberately below the prompt's 250-char target: a genuinely sharp
# 160-char reply shouldn't be gated out just for being concise. The ceiling
# guards against the model dumping a blog paragraph.
_MIN_CHARS = 150
_MAX_CHARS = 900

# "not just X, it's Y" and cousins — the single most-cited LLM tell.
_NOT_JUST_RE = re.compile(r"\b(not just|isn'?t just|aren'?t just)\b", re.IGNORECASE)
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF☀-➿]")

# Disclosed-mention markers. Any Zenskar mention without one of these is
# undisclosed posing (astroturfing) and gets rejected outright.
_DISCLOSURE_MARKERS = ("work at zenskar", "zenskar team", "i'm at zenskar", "im at zenskar")

_client = None


@dataclass
class Draft:
    comment: str
    mention: str
    rationale: str
    skip: bool
    skip_reason: str | None


def quality_gate(comment: str) -> str | None:
    """Return a rejection reason, or None when the draft is clean."""
    lowered = comment.lower()
    for banned in AI_TELL_BANS:
        if banned.lower() in lowered:
            return f"banned substring: {banned!r}"
    if _NOT_JUST_RE.search(comment):
        return "banned construction: 'not just X, it's Y'"
    if _EMOJI_RE.search(comment):
        return "emoji"
    if not _MIN_CHARS <= len(comment) <= _MAX_CHARS:
        return f"length {len(comment)} outside {_MIN_CHARS}-{_MAX_CHARS}"
    if "zenskar" in lowered and not any(m in lowered for m in _DISCLOSURE_MARKERS):
        return "zenskar mention without disclosure"
    return None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-flash-latest")


def draft(candidate: dict, thread_digest: str) -> Draft | None:
    """Generate a draft for one candidate. Returns None on API/parse errors
    (transient — candidate is retried next run). A Draft with skip=True or a
    failing quality gate is a deliberate refusal (recorded as 'rejected')."""
    from google.genai import types

    competitors = candidate.get("mentioned_competitors") or []
    pain_points = candidate.get("pain_points") or []
    grounding = bofu.grounding_for(competitors, pain_points, candidate["title"])

    user_msg = draft_user_message(
        subreddit=candidate.get("subreddit"),
        kind=candidate["kind"],
        title=candidate["title"],
        thread_digest=thread_digest,
        bucket=candidate["bucket"],
        pain_points=pain_points,
        mentioned_competitors=competitors,
        grounding_facts=grounding,
    )
    try:
        resp = _get_client().models.generate_content(
            model=model_name(),
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=DRAFT_SYSTEM,
                response_mime_type="application/json",
                temperature=0.7,
            ),
        )
        raw = json.loads(resp.text)
    except Exception as e:
        print(f"[drafter] generate/parse failed for {candidate['post_id']}: {e}")
        return None

    if not isinstance(raw, dict):
        print(f"[drafter] non-object JSON for {candidate['post_id']}")
        return None

    return Draft(
        comment=(raw.get("comment") or "").strip(),
        mention=raw.get("mention") or "none",
        rationale=raw.get("rationale") or "",
        skip=bool(raw.get("skip")),
        skip_reason=raw.get("skip_reason"),
    )
