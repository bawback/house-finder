"""Telegram message text (Persian, with listing data kept in English)."""
from __future__ import annotations

from .matcher import Verdict
from .models import Listing
from .telegram import esc

TYPE_FA = {
    "detached": "دیتچ", "semi-detached": "سمی‌دیتچ", "end-of-terrace": "اند‌آو‌ترس",
    "terraced": "ترس", "apartment": "آپارتمان",
}
SOURCE_NAME = {"daft": "Daft.ie", "myhome": "MyHome.ie", "propertyie": "Property.ie"}


def fmt_price(p: int | None) -> str:
    return f"€{p:,}" if p else "نامشخص"


def listing_message(l: Listing, v: Verdict) -> str:
    lines = [f"🏡 <b>{esc(l.address or 'آگهی جدید')}</b>",
             f"💰 {fmt_price(l.price)}   ⭐ امتیاز: {v.score}"]
    facts = []
    if l.property_type:
        facts.append(TYPE_FA.get(l.property_type, l.property_type))
    if l.bedrooms:
        facts.append(f"{l.bedrooms} خواب")
    if l.bathrooms:
        facts.append(f"{l.bathrooms} حمام")
    if l.ber:
        facts.append(f"BER {l.ber}")
    if l.parking:
        facts.append(f"پارکینگ {l.parking}")
    if l.floor_area_m2:
        facts.append(f"{l.floor_area_m2:g} m²")
    if l.new_build:
        facts.append("نوساز")
    if facts:
        lines.append("🔎 " + " · ".join(facts))
    lines += [esc(n) for n in v.notes]
    if l.viewings:
        lines.append("📅 بازدید: " + esc(" | ".join(l.viewings)))
    agent = " ".join(x for x in (l.agent_name, l.agent_phone) if x)
    if agent:
        lines.append(f"📞 {esc(agent)}")
    if not l.details_fetched:
        lines.append("ℹ️ جزئیات صفحه خوانده نشد، اطلاعات از ایمیل هشدار است.")
    lines.append(f'🔗 <a href="{esc(l.url)}">مشاهده در {SOURCE_NAME.get(l.source, l.source)}</a>')
    return "\n".join(lines)


def listing_buttons(l: Listing) -> list[list[dict]]:
    return [[{"text": "🔗 باز کردن آگهی", "url": l.url},
             {"text": "📅 درخواست بازدید", "callback_data": f"v:{l.id}"}]]


def viewing_request_text(l: Listing, contact: dict) -> str:
    name = contact.get("name") or "[your name]"
    phone = contact.get("phone") or "[your phone]"
    email = contact.get("email") or "[your email]"
    addr = l.address or l.url
    return (f"Hello,\n\nWe are very interested in {addr} ({l.url}) and would like to arrange a viewing "
            f"at the earliest available time. We are first-time buyers "
            f"and are flexible on times, including evenings and weekends.\n\n"
            f"Kind regards,\n{name}\n{phone}\n{email}")


HELP = """<b>دستورها</b>
/prefs نمایش معیارها
/budget 700000 سقف قیمت
/beds 2 4 حداقل و حداکثر خواب (اختیاری: /beds 2 4 3 که آخری ایده‌آل است)
/baths 2 حداقل حمام
/ber B3 حداقل برچسب انرژی
/parking 1 حداقل پارکینگ
/types detached semi-detached end-of-terrace terraced apartment
   (ترتیب = اولویت)
/areas فهرست محله‌ها
/addarea Howth اضافه کردن محله
/removearea Bray حذف محله
/contact Babak Smith | 0871234567 | me@email.com
   مشخصات شما برای درخواست بازدید
/viewing کد ـ متن درخواست بازدید برای یک آگهی
/pause و /resume توقف و ادامهٔ ارسال
/reset بازگشت به تنظیمات اولیه

ربات هر حدود ۳۰ دقیقه یک بار اجرا می‌شود، پس جواب دستورها ممکن است تا ۳۰ دقیقه طول بکشد."""


def prefs_summary(p: dict, paused: bool) -> str:
    b, beds, baths = p.get("budget", {}), p.get("bedrooms", {}), p.get("bathrooms", {})
    types = "، ".join(TYPE_FA.get(t, t) for t in p.get("property_types", []))
    c = p.get("contact", {})
    return "\n".join([
        "<b>معیارهای فعلی</b>" + ("  ⏸️ (متوقف)" if paused else ""),
        f"💰 سقف قیمت: {fmt_price(b.get('max'))} (Help to Buy تا {fmt_price(b.get('htb_max'))})",
        f"🏠 نوع (به ترتیب اولویت): {types}",
        f"🛏 خواب: {beds.get('min')} تا {beds.get('max')} (ایده‌آل {beds.get('ideal')})",
        f"🛁 حمام: حداقل {baths.get('min')}",
        f"⚡ BER: حداقل {p.get('min_ber')}",
        f"🚗 پارکینگ: حداقل {p.get('parking_min')}",
        f"🏢 آپارتمان: حداقل {p.get('apartment_min_bedrooms')} خواب، تا {fmt_price(p.get('apartment_max_price'))}",
        f"📍 {len(p.get('areas') or [])} محله (/areas)",
        f"👤 تماس: {esc(c.get('name') or '-')} {esc(c.get('phone') or '')} {esc(c.get('email') or '')}",
    ])
