"""Handle Telegram commands and button taps."""
from __future__ import annotations

import logging
import os
from typing import Callable

from .messages import HELP, prefs_summary, viewing_request_text
from .models import BER_ORDER, Listing
from .state import State
from .telegram import Telegram, esc

log = logging.getLogger(__name__)

VALID_TYPES = ["detached", "semi-detached", "end-of-terrace", "terraced", "apartment"]
TYPE_ALIASES = {"semi": "semi-detached", "semid": "semi-detached", "end": "end-of-terrace",
                "terrace": "terraced", "flat": "apartment", "apt": "apartment"}

# send_email(to, subject, body, reply_to) -> None; None when email isn't configured.
EmailSender = Callable[[str, str, str, str | None], None] | None


def _int(s: str) -> int:
    return int(s.replace(",", "").replace("€", "").replace("k", "000"))


def handle_command(text: str, state: State, send_email: EmailSender = None) -> str:
    """Apply one command to the state and return the reply text."""
    parts = text.strip().split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    p = state.prefs
    try:
        if cmd in ("/help", "/start"):
            return HELP
        if cmd == "/prefs":
            return prefs_summary(p, state.data["paused"])
        if cmd == "/budget":
            p["budget"]["max"] = _int(arg)
            return f"✅ سقف قیمت: €{p['budget']['max']:,}"
        if cmd == "/beds":
            nums = [int(x) for x in arg.split()]
            p["bedrooms"]["min"] = nums[0]
            if len(nums) > 1:
                p["bedrooms"]["max"] = nums[1]
            if len(nums) > 2:
                p["bedrooms"]["ideal"] = nums[2]
            b = p["bedrooms"]
            return f"✅ خواب: {b['min']} تا {b['max']} (ایده‌آل {b['ideal']})"
        if cmd == "/baths":
            p["bathrooms"]["min"] = int(arg)
            return f"✅ حداقل حمام: {arg}"
        if cmd == "/ber":
            rating = arg.upper()
            if rating not in BER_ORDER:
                return "❌ یکی از این‌ها را بنویسید: " + " ".join(BER_ORDER)
            p["min_ber"] = rating
            return f"✅ حداقل BER: {rating}"
        if cmd == "/parking":
            p["parking_min"] = int(arg)
            return f"✅ حداقل پارکینگ: {arg}"
        if cmd == "/types":
            types = [TYPE_ALIASES.get(t.lower(), t.lower()) for t in arg.replace(",", " ").split()]
            bad = [t for t in types if t not in VALID_TYPES]
            if bad or not types:
                return "❌ نوع نامعتبر. مجاز: " + " ".join(VALID_TYPES)
            p["property_types"] = types
            return "✅ نوع‌ها به ترتیب اولویت: " + " ← ".join(types)
        if cmd == "/areas":
            areas = p.get("areas") or []
            return "<b>محله‌ها</b>\n" + (esc("، ".join(areas)) if areas else "همه‌جا")
        if cmd == "/addarea":
            if not arg:
                return "❌ اسم محله را بنویسید، مثلاً /addarea Howth"
            p.setdefault("areas", [])
            if arg.lower() not in (a.lower() for a in p["areas"]):
                p["areas"].append(arg)
            return f"✅ اضافه شد: {esc(arg)}"
        if cmd == "/removearea":
            before = len(p.get("areas") or [])
            p["areas"] = [a for a in p.get("areas") or [] if a.lower() != arg.lower()]
            return f"✅ حذف شد: {esc(arg)}" if len(p["areas"]) < before else f"❌ پیدا نشد: {esc(arg)}"
        if cmd == "/avoid":
            if not arg:
                avoid = p.get("avoid_areas") or []
                return "<b>محله‌های ممنوع</b>\n" + (esc("، ".join(avoid)) if avoid else "هیچ")
            p.setdefault("avoid_areas", [])
            if arg.lower() not in (a.lower() for a in p["avoid_areas"]):
                p["avoid_areas"].append(arg)
            return f"🚫 به محله‌های ممنوع اضافه شد: {esc(arg)}"
        if cmd == "/unavoid":
            before = len(p.get("avoid_areas") or [])
            p["avoid_areas"] = [a for a in p.get("avoid_areas") or [] if a.lower() != arg.lower()]
            return f"✅ از محله‌های ممنوع حذف شد: {esc(arg)}" if len(p["avoid_areas"]) < before else f"❌ پیدا نشد: {esc(arg)}"
        if cmd == "/contact":
            fields = [x.strip() for x in arg.split("|")]
            if len(fields) != 3:
                return "❌ این‌طور بنویسید: /contact نام | تلفن | ایمیل"
            p["contact"] = dict(zip(("name", "phone", "email"), fields))
            return "✅ مشخصات تماس ذخیره شد."
        if cmd == "/all":
            state.data["full_sweep_requested"] = True
            return "🔎 در اجرای بعدی همهٔ آگهی‌های فعلی Daft و MyHome بررسی می‌شوند و موارد مناسب فرستاده می‌شوند."
        if cmd == "/pause":
            state.data["paused"] = True
            return "⏸️ ارسال آگهی متوقف شد. برای ادامه /resume"
        if cmd == "/resume":
            state.data["paused"] = False
            return "▶️ ارسال آگهی ادامه پیدا کرد."
        if cmd == "/reset":
            state.reset_prefs()
            return "♻️ معیارها به حالت اولیه برگشت."
        if cmd == "/viewing":
            return viewing_reply(arg, state, send_email)
    except (ValueError, IndexError, KeyError):
        return "❌ دستور را درست وارد نکردید. /help را ببینید."
    return "دستور ناشناخته. /help را ببینید."


def viewing_reply(listing_id: str, state: State, send_email: EmailSender) -> str:
    data = state.data["sent"].get(listing_id.strip())
    if not data:
        return "❌ این آگهی پیدا نشد (کد را از دکمهٔ درخواست بازدید بگیرید)."
    listing = Listing.from_dict(data)
    contact = state.prefs.get("contact") or {}
    body = viewing_request_text(listing, contact)
    if listing.agent_email and send_email and contact.get("email"):
        send_email(listing.agent_email, f"Viewing request: {listing.address}", body, contact["email"])
        return (f"✅ درخواست بازدید به {esc(listing.agent_email)} ایمیل شد و جواب به "
                f"{esc(contact['email'])} می‌رسد.\n\n<pre>{esc(body)}</pre>")
    lines = ["📅 <b>درخواست بازدید</b>"]
    if listing.agent_phone:
        lines.append(f"📞 تماس با {esc(listing.agent_name or 'آژانس')}: {esc(listing.agent_phone)}")
    lines.append("ایمیل آژانس در آگهی نبود. این متن را کپی کنید و در فرم «Email agent» آگهی بفرستید:")
    if not contact.get("name"):
        lines.append("(اول با /contact مشخصاتتان را ثبت کنید تا متن کامل شود.)")
    lines.append(f"<pre>{esc(body)}</pre>")
    lines.append(f'<a href="{esc(listing.url)}">باز کردن آگهی</a>')
    return "\n".join(lines)


def process_updates(tg: Telegram, state: State, pair_code: str, send_email: EmailSender = None) -> None:
    updates = tg.get_updates(state.data["telegram_offset"])
    for u in updates:
        state.data["telegram_offset"] = u["update_id"] + 1
        if "callback_query" in u:
            cq = u["callback_query"]
            chat_id = cq.get("message", {}).get("chat", {}).get("id")
            if chat_id not in state.data["chats"]:
                continue
            tg.answer_callback(cq["id"])
            if cq.get("data", "").startswith("v:"):
                tg.send(chat_id, viewing_reply(cq["data"][2:], state, send_email))
            continue
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = msg.get("chat", {}).get("id")
        if not text.startswith("/") or chat_id is None:
            continue
        if chat_id not in state.data["chats"]:
            # Only chats that know the pairing code may use the bot, and only while no chat is
            # paired yet (or ALLOW_NEW_CHAT is set), so a leaked code cannot add a stranger.
            open_to_new = not state.data["chats"] or os.environ.get("ALLOW_NEW_CHAT") == "1"
            if (open_to_new and text.split()[0].split("@")[0] == "/start" and pair_code
                    and text.split()[1:2] == [pair_code]):
                state.data["chats"].append(chat_id)
                tg.send(chat_id, "✅ این گفتگو وصل شد. آگهی‌های مناسب اینجا فرستاده می‌شوند.\n\n" + HELP)
            else:
                tg.send(chat_id, "این ربات خصوصی است.")
            continue
        try:
            tg.send(chat_id, handle_command(text, state, send_email))
        except Exception:
            log.exception("command failed: %s", text)
            tg.send(chat_id, "❌ خطایی پیش آمد.")
