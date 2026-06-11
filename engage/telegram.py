"""Thin Telegram Bot API client (plain HTTPS, no SDK) shared by the CI
drafter (send drafts with Approve/Skip buttons) and the local poster
(poll button taps, confirm posts).

Long polling via getUpdates means no public webhook is needed — the local
poster fetches pending taps each tick; Telegram retains updates for 24h.
"""

import os

import requests

_TIMEOUT = 30

# callback_data prefixes (Telegram caps callback_data at 64 bytes; a
# prefixed post_id like "ap:t3_abc123" fits comfortably).
CB_APPROVE = "ap:"
CB_SKIP = "sk:"


def _token() -> str:
    return os.environ["TELEGRAM_BOT_TOKEN"]


def chat_id() -> str:
    return os.environ["TELEGRAM_CHAT_ID"]


def _call(method: str, payload: dict) -> dict:
    resp = requests.post(
        f"https://api.telegram.org/bot{_token()}/{method}",
        json=payload,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"telegram {method} failed: {data}")
    return data["result"]


def build_draft_message(candidate: dict, draft_text: str) -> str:
    """Plain text (no parse_mode) so titles with markdown chars can't break
    rendering."""
    return (
        f"r/{candidate.get('subreddit')} · {candidate['bucket']} · {candidate['kind']}\n"
        f"{candidate['title']}\n\n"
        f"{candidate['permalink']}\n\n"
        f"DRAFT:\n{draft_text}\n\n"
        f"(reply to this message with your own text to post an edited version)"
    )


def send_draft(candidate: dict, draft_text: str) -> int:
    """Send a draft for approval; returns the Telegram message_id used later
    to match edit-replies back to the draft."""
    result = _call("sendMessage", {
        "chat_id": chat_id(),
        "text": build_draft_message(candidate, draft_text),
        "disable_web_page_preview": True,
        "reply_markup": {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": CB_APPROVE + candidate["post_id"]},
                {"text": "❌ Skip", "callback_data": CB_SKIP + candidate["post_id"]},
            ]],
        },
    })
    return result["message_id"]


def send_text(text: str) -> None:
    _call("sendMessage", {
        "chat_id": chat_id(),
        "text": text,
        "disable_web_page_preview": True,
    })


def get_updates(offset: int | None) -> list[dict]:
    payload: dict = {"timeout": 0, "allowed_updates": ["callback_query", "message"]}
    if offset is not None:
        payload["offset"] = offset
    return _call("getUpdates", payload)


def answer_callback(callback_query_id: str, text: str) -> None:
    _call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


def edit_message(message_id: int, text: str) -> None:
    """Rewrite a draft message (e.g. to append its resolution) and drop the
    buttons so a stale tap can't fire twice."""
    _call("editMessageText", {
        "chat_id": chat_id(),
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": True,
    })
