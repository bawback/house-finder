"""One run: read Telegram commands, read new alert emails, send matching listings.

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
from .telegram import Telegram

log = logging.getLogger("house_finder")

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36 house-finder-personal")
PAGE_DELAY_SECONDS = 3      # be gentle: one listing page at a time, a few seconds apart
MAX_PAGES_PER_RUN = 40


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


def run(state_path: Path, dry_run: bool = False) -> int:
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

    links: list[tuple[str, str]] = []
    if gmail and gmail_pw:
        try:
            links, state.data["last_email_uid"] = fetch_alert_emails(
                gmail, gmail_pw, state.data["last_email_uid"], http)
        except Exception:
            log.exception("reading Gmail failed")
    else:
        log.warning("GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set")

    new = [(src, url) for src, url in links if not state.is_seen(url)]
    log.info("%d listing link(s) in new emails, %d not seen before", len(links), len(new))

    sent = 0
    for i, (source, url) in enumerate(new):
        listing = Listing(url=url, source=source)
        if i < MAX_PAGES_PER_RUN:
            if i:
                time.sleep(PAGE_DELAY_SECONDS)
            fetch_details(listing, http)
        listing.address = listing.address or address_from_url(url)
        verdict = evaluate(listing, state.prefs)
        state.mark_seen(url)
        if not verdict.ok:
            log.info("skip %s: %s", url, "; ".join(verdict.reasons))
            continue
        if state.data["paused"]:
            continue
        data = listing.to_dict()
        data["_sent_at"] = int(time.time())
        state.data["sent"][listing.id] = data
        text = listing_message(listing, verdict)
        if dry_run or not tg:
            print(text, "\n")
            continue
        for chat_id in state.data["chats"]:
            try:
                tg.send(chat_id, text, listing_buttons(listing), photo=listing.image)
                sent += 1
            except Exception:
                log.exception("sending listing failed")

    if not state.data["chats"] and tg:
        log.warning("No Telegram chat is paired yet. Send /start %s in your group.", "<PAIR_CODE>")
    state.save()
    log.info("sent %d message(s)", sent)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Irish house listing alerts to Telegram")
    ap.add_argument("--state", default="data/state.json", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="print matches instead of sending")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return run(args.state, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
