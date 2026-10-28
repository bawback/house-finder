from __future__ import annotations

import html
import logging

import requests

log = logging.getLogger(__name__)


def esc(s) -> str:
    return html.escape(str(s), quote=False)


class Telegram:
    def __init__(self, token: str, session: requests.Session | None = None):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.http = session or requests.Session()

    def _call(self, method: str, **params):
        r = self.http.post(self.base + method, json=params, timeout=30)
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram {method} failed: {data.get('description')}")
        return data["result"]

    def get_updates(self, offset: int) -> list[dict]:
        return self._call("getUpdates", offset=offset, timeout=0,
                          allowed_updates=["message", "callback_query"])

    def send(self, chat_id: int, text: str, buttons: list[list[dict]] | None = None,
             photo: str | None = None) -> None:
        markup = {"inline_keyboard": buttons} if buttons else None
        if photo and len(text) <= 1024:
            try:
                self._call("sendPhoto", chat_id=chat_id, photo=photo, caption=text,
                           parse_mode="HTML", **({"reply_markup": markup} if markup else {}))
                return
            except RuntimeError as e:
                log.info("photo failed, sending text only: %s", e)
        for i in range(0, len(text), 4000):
            self._call("sendMessage", chat_id=chat_id, text=text[i:i + 4000], parse_mode="HTML",
                       **({"reply_markup": markup} if markup and i + 4000 >= len(text) else {}))

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except RuntimeError as e:
            # Callbacks expire after a while; the bot only runs every ~30 minutes.
            log.info("callback answer failed: %s", e)
