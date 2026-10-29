"""Read listing alert emails (Daft, MyHome, Property.ie, agents) from the bot's Gmail inbox."""
from __future__ import annotations

import email
import imaplib
import logging
import re
from email.header import decode_header, make_header
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


LISTING_PATTERNS = {
    "daft": re.compile(r"^https://www\.daft\.ie/(?:for-sale|new-home-for-sale|new-home|new-homes-for-sale)/[^/?#]+/\d+"),
    "myhome": re.compile(r"^https://www\.myhome\.ie/(?:residential|newhomes)/brochure/[^/?#]+/\d+"),
    "propertyie": re.compile(r"^https://www\.property\.ie/property-for-sale/[^?#]+?/\d+[^/?#]*/?"),
}

# Links in alert emails are often wrapped by click trackers.
TRACKER_HINTS = ("click.", "links.", "email.", "track", "url?", "/ls/click", "sendgrid", "mailchi.mp", "list-manage")


def canonical(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if "property.ie" in parts.netloc:
        path += "/"
    return urlunsplit(("https", parts.netloc.lower(), path, "", ""))


def classify(url: str) -> tuple[str, str] | None:
    """Return (source, canonical_url) if url is a listing page we understand."""
    url = canonical(url)
    for source, pattern in LISTING_PATTERNS.items():
        m = pattern.match(url)
        if m:
            return source, canonical(m.group(0))
    return None


def _unwrap(url: str, session: requests.Session | None) -> str:
    """Find the real destination of a tracked link."""
    # Many trackers carry the destination in a query parameter.
    for values in parse_qs(urlsplit(url).query).values():
        for v in values:
            v = unquote(v)
            if v.startswith("http") and classify(v):
                return v
    if session and any(h in url for h in TRACKER_HINTS):
        try:
            r = session.head(url, allow_redirects=True, timeout=15)
            return r.url
        except requests.RequestException as e:
            log.info("could not resolve tracked link %s: %s", url[:80], e)
    return url


def extract_listing_links(html_or_text: str, session: requests.Session | None = None) -> list[tuple[str, str]]:
    """All distinct listing URLs found in an email body, in order."""
    candidates: list[str] = []
    if "<" in html_or_text:
        soup = BeautifulSoup(html_or_text, "html.parser")
        candidates += [a["href"] for a in soup.find_all("a", href=True)]
    candidates += re.findall(r"https?://[^\s\"'<>)]+", html_or_text)

    found: dict[str, str] = {}
    for raw in candidates:
        raw = raw.replace("&amp;", "&").strip()
        if raw.startswith("http://"):
            raw = "https://" + raw[len("http://"):]
        hit = classify(raw) or classify(_unwrap(raw, session))
        if hit:
            found.setdefault(hit[1], hit[0])
    return [(src, url) for url, src in found.items()]


def _body(msg: email.message.Message) -> str:
    html, text = [], []
    for part in msg.walk():
        ctype = part.get_content_type()
        if part.get_content_maintype() == "multipart":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        decoded = payload.decode(charset, errors="replace")
        (html if ctype == "text/html" else text).append(decoded)
    return "\n".join(html) + "\n" + "\n".join(text)


def fetch_alert_emails(address: str, app_password: str, last_uid: int,
                       session: requests.Session | None = None) -> tuple[list[tuple[str, str]], int]:
    """Return listing links from emails newer than last_uid, plus the new highest uid."""
    links: list[tuple[str, str]] = []
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    try:
        imap.login(address, app_password)
        imap.select("INBOX")
        # On the very first run only look at the last few days.
        criteria = f"UID {last_uid + 1}:*" if last_uid else "SINCE " + _days_ago(3)
        status, data = imap.uid("search", None, criteria)
        uids = [int(u) for u in (data[0].split() if status == "OK" and data[0] else [])]
        uids = [u for u in uids if u > last_uid]
        for uid in uids:
            status, parts = imap.uid("fetch", str(uid), "(RFC822)")
            if status != "OK" or not parts or parts[0] is None:
                continue
            # Any email counts, so alerts you forward and agent newsletters work too.
            msg = email.message_from_bytes(parts[0][1])
            sender = str(make_header(decode_header(msg.get("From", ""))))
            found = extract_listing_links(_body(msg), session)
            log.info("email uid %s from %s: %d listing link(s)", uid, sender, len(found))
            links += found
            last_uid = max(last_uid, uid)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return links, last_uid


def _days_ago(n: int) -> str:
    import datetime as dt
    return (dt.date.today() - dt.timedelta(days=n)).strftime("%d-%b-%Y")
