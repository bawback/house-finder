"""One run: read Telegram commands, find listings (alert emails and search pages), send matches.

Configuration comes from environment variables (GitHub Actions secrets):
  TELEGRAM_BOT_TOKEN   from @BotFather
  PAIR_CODE            any secret word; send "/start <word>" in your Telegram group once
  GMAIL_ADDRESS        the bot's Gmail address
  GMAIL_APP_PASSWORD   a Gmail app password (not the normal password)
"""
from __future__ import annotations

import argparse
import logging
import os
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path

import requests

from .alerts import fetch_alert_emails
from .commands import process_updates
from .matcher import evaluate
from .messages import listing_buttons, listing_message
from .models import Listing
from .parse import parse_listing_page
from .state import State
from .sweep import run_searches, searches_for
from .telegram import Telegram

log = logging.getLogger("house_finder")

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36 house-finder-personal")
PAGE_DELAY_SECONDS = 3      # be gentle: one listing page at a time, a few seconds apart


def make_email_sender(address: str, password: str):
    def send(to: str, subject: str, body: str, reply_to: str | None) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = address, to, subject
        if reply_to:
            msg["Reply-To"] = reply_to
            msg["Cc"] = reply_to
        msg.set_content(body)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(address, password)
            s.send_message(msg)
    return send


def address_from_url(url: str) -> str:
    """Listing URLs carry the address as a slug, e.g. /for-sale/12-oak-road-blackrock-co-dublin/123."""
    parts = [p for p in url.split("/") if p]
    slug = next((p for p in reversed(parts) if not p.isdigit() and "-" in p), "")
    return slug.replace("-", " ").title()


def fetch_details(listing: Listing, http: requests.Session) -> Listing:
    try:
        r = http.get(listing.url, timeout=25)
        if r.status_code == 200:
            return parse_listing_page(listing, r.text)
        log.warning("listing page %s returned %s", listing.url, r.status_code)
    except requests.RequestException as e:
        log.warning("listing page %s failed: %s", listing.url, e)
    return listing


MAX_DETAIL_FETCHES = 80     # listing pages opened per run
MAX_SEND_PER_RUN = 40       # Telegram groups allow about 20 messages a minute
SEND_DELAY_SECONDS = 3
FULL_SWEEP_EVERY_HOURS = 20


def gather(state: State, http: requests.Session, gmail: str, gmail_pw: str, full_sweep: bool) -> list[Listing]:
    """Listings to consider this run: leftovers, alert emails, and search pages."""
    found: dict[str, Listing] = {}
    for url, data in state.data["pending"].items():
        found[url] = Listing.from_dict(data)

    if gmail and gmail_pw:
        try:
            links, state.data["last_email_uid"] = fetch_alert_emails(
                gmail, gmail_pw, state.data["last_email_uid"], http)
            log.info("%d listing link(s) in new emails", len(links))
            for source, url in links:
                found.setdefault(url, Listing(url=url, source=source))
        except Exception:
            log.exception("reading Gmail failed")
    else:
        log.warning("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set")

    try:
        if full_sweep:
            listings, stats = run_searches(searches_for(state.prefs), http,
                                           debug_dir=state.path.parent / "debug")
            state.data["last_full_sweep"] = int(time.time())
        else:
            # Quick check between full sweeps: the newest page of each Daft search.
            listings, stats = run_searches(searches_for(state.prefs, newest_first=True), http, max_pages=1)
        state.data["sweep_stats"] = stats
        for l in listings:
            found.setdefault(l.url, l)
    except Exception:
        log.exception("search pages failed")

    return [l for url, l in found.items() if not state.is_seen(url)]


def save_samples(state: State, http: requests.Session) -> None:
    """Save raw copies of a few pages to debug/ on the state branch, to check the parsers."""
    out = state.path.parent / "debug"
    out.mkdir(parents=True, exist_ok=True)
    urls = {"myhome-search": "https://www.myhome.ie/residential/dublin-14/house-for-sale",
            "daft-search": searches_for(state.prefs)[0].url}
    for i, url in enumerate(list(state.data["pending"])[:3]):
        urls[f"listing-{i}"] = url
    for name, url in urls.items():
        try:
            r = http.get(url, timeout=25)
            body = f"<!-- {url} HTTP {r.status_code} -->\n" + r.text[:800_000]
        except requests.RequestException as e:
            body = f"<!-- {url} failed: {e} -->"
        (out / f"{name}.html").write_text(body, encoding="utf-8")
        time.sleep(PAGE_DELAY_SECONDS)


def run(state_path: Path, dry_run: bool = False, force_full_sweep: bool = False) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    gmail = os.environ.get("GMAIL_ADDRESS", "")
    gmail_pw = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    pair_code = os.environ.get("PAIR_CODE", "")

    state = State.load(state_path)
    http = requests.Session()
    http.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-IE,en;q=0.9"})
    tg = Telegram(token) if token else None
    send_email = make_email_sender(gmail, gmail_pw) if gmail and gmail_pw else None

    if tg:
        try:
            process_updates(tg, state, pair_code, send_email)
        except Exception:
            log.exception("reading Telegram updates failed")
    else:
        log.warning("TELEGRAM_BOT_TOKEN not set")

    if state.data.pop("save_samples", False):
        save_samples(state, http)

    requested = state.data.pop("full_sweep_requested", False)
    due = time.time() - state.data.get("last_full_sweep", 0) > FULL_SWEEP_EVERY_HOURS * 3600
    full = force_full_sweep or requested or due
    first_sweep = not state.data.get("last_full_sweep")
    candidates = gather(state, http, gmail, gmail_pw, full)
    log.info("%d listing(s) not seen before (full sweep: %s)", len(candidates), full)

    matches: list[tuple[Listing, object]] = []
    pending: dict[str, dict] = {}
    fetched = 0
    for listing in candidates:
        listing.address = listing.address or address_from_url(listing.url)
        # Search cards already say price, beds and so on: skip clear misses without opening the page.
        if not evaluate(listing, state.prefs).ok:
            state.mark_seen(listing.url)
            continue
        if not listing.details_fetched:
            if fetched >= MAX_DETAIL_FETCHES:
                pending[listing.url] = listing.to_dict()
                continue
            if fetched:
                time.sleep(PAGE_DELAY_SECONDS)
            fetched += 1
            fetch_details(listing, http)
        verdict = evaluate(listing, state.prefs)
        if not verdict.ok:
            log.info("skip %s: %s", listing.url, "; ".join(verdict.reasons))
            state.mark_seen(listing.url)
            continue
        matches.append((listing, verdict))

    matches.sort(key=lambda m: m[1].score, reverse=True)
    sent = 0
    for listing, verdict in matches:
        if state.data["paused"]:
            state.mark_seen(listing.url)
            continue
        if sent >= MAX_SEND_PER_RUN:
            pending[listing.url] = listing.to_dict()
            continue
        data = listing.to_dict()
        data["_sent_at"] = int(time.time())
        state.data["sent"][listing.id] = data
        state.mark_seen(listing.url)
        text = listing_message(listing, verdict)
        if dry_run or not tg:
            print(text, "\n")
            sent += 1
            continue
        for chat_id in state.data["chats"]:
            try:
                if sent:
                    time.sleep(SEND_DELAY_SECONDS)
                tg.send(chat_id, text, listing_buttons(listing), photo=listing.image)
            except Exception:
                log.exception("sending listing failed")
        sent += 1
    state.data["pending"] = pending

    if tg and (requested or first_sweep) and full and not dry_run:
        msg = f"🔎 جستجوی کامل تمام شد: {len(matches)} آگهی مناسب پیدا شد و {sent} تا فرستاده شد."
        if pending:
            msg += f"\n⏳ {len(pending)} آگهی دیگر در اجراهای بعدی (هر ۳۰ دقیقه) فرستاده می‌شود."
        for chat_id in state.data["chats"]:
            tg.send(chat_id, msg)

    if not state.data["chats"] and tg:
        log.warning("No Telegram chat is paired yet. Send /start <PAIR_CODE> in your group.")
    state.save()
    log.info("sent %d listing(s), %d pending", sent, len(pending))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Irish house listing alerts to Telegram")
    ap.add_argument("--state", default="data/state.json", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="print matches instead of sending")
    ap.add_argument("--full-sweep", action="store_true", help="read every search page now")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return run(args.state, args.dry_run, args.full_sweep)


if __name__ == "__main__":
    sys.exit(main())
