import os

from groq import Groq

from classify import groq_quota
from classify.prompts import RELEVANCE_SYSTEM

_client = None

# llama-3.1-8b-instant: ~500K tokens/day on Groq free tier (vs 200K for
# gpt-oss-120b). Plenty of headroom for a YES/NO noise filter, and the 8B
# model handles this binary task well.
_MODEL = "llama-3.1-8b-instant"


class RelevanceRateLimited(Exception):
    """Stage-1 could not run because the Groq quota is exhausted. Caller should
    treat the hit as deferred (do NOT upsert) so it gets reconsidered next run."""


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def is_relevant(title: str, body: str | None) -> bool:
    """Return True if the post passes stage-1 noise filter. Raises
    RelevanceRateLimited when Groq returns 429 so callers can defer rather
    than silently treat it as a NO."""
    text = title
    if body:
        text += "\n\n" + body[:400]
    try:
        resp = groq_quota.chat_complete(
            _get_client(),
            model=_MODEL,
            messages=[
                {"role": "system", "content": RELEVANCE_SYSTEM},
                {"role": "user", "content": text[:800]},
            ],
            max_tokens=3,
            temperature=0,
        )
        answer = resp.choices[0].message.content.strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        msg = str(e)
        if "429" in msg or "rate_limit" in msg.lower():
            raise RelevanceRateLimited(msg) from e
        print(f"[relevance] Groq error: {e}")
        return False
