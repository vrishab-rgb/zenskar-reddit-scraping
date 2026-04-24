import os

from groq import Groq

from classify.prompts import RELEVANCE_SYSTEM

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.environ["GROQ_API_KEY"])
    return _client


def is_relevant(title: str, body: str | None) -> bool:
    text = title
    if body:
        text += "\n\n" + body[:1500]
    try:
        resp = _get_client().chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": RELEVANCE_SYSTEM},
                {"role": "user", "content": text[:2500]},
            ],
            max_tokens=5,
            temperature=0,
        )
        answer = resp.choices[0].message.content.strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        print(f"[relevance] Groq error: {e}")
        return False
