"""Read search result pages on Daft and MyHome to find every current listing.

Only URL forms that each site's robots.txt allows are used:
- Daft: /property-for-sale/<county>/houses with filter and page parameters.
- MyHome: /residential/<area>/house-for-sale with a bare ?page=N (any other query
  parameter is disallowed there, so filtering happens here instead).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from .alerts import classify
from .models import BER_ORDER, Listing
from .parse import BATHS_RE, BEDS_RE, normalise_type, parse_price

log = logging.getLogger(__name__)

PAGE_DELAY_SECONDS = 2
MAX_PAGES_PER_SEARCH = 40

DAFT_COUNTIES = ["dublin", "wicklow", "kildare", "meath"]
MYHOME_AREAS = ["dublin-4", "dublin-6", "dublin-6w", "dublin-14", "dublin-16", "dublin-18",
                "dublin-3", "dublin-13", "dublin-15", "south-county-dublin", "north-county-dublin",
                "wicklow", "kildare", "meath"]


@dataclass
class Search:
    name: str
    source: str
    url: str

    def page_url(self, page: int) -> str:
        if page == 1:
            return self.url
        joiner = "&" if "?" in self.url else "?"
        return f"{self.url}{joiner}page={page}"


def searches_for(prefs: dict, newest_first: bool = False) -> list[Search]:
    beds, baths = prefs.get("bedrooms", {}), prefs.get("bathrooms", {})
    params = {"salePrice_to": prefs.get("budget", {}).get("max", 700000),
              "numBeds_from": beds.get("min", 1), "numBaths_from": baths.get("min", 1)}
    if beds.get("max"):
        params["numBeds_to"] = beds["max"]
    if newest_first:
        params["sort"] = "publishDateDesc"
    kind = "houses" if "apartment" not in prefs.get("property_types", []) else ""
    out = []
    for county in prefs.get("sweep", {}).get("daft_counties", DAFT_COUNTIES):
        path = f"https://www.daft.ie/property-for-sale/{county}" + (f"/{kind}" if kind else "")
        out.append(Search(f"daft-{county}", "daft", f"{path}?{urlencode(params)}"))
    if not newest_first:
        for area in prefs.get("sweep", {}).get("myhome_areas", MYHOME_AREAS):
            out.append(Search(f"myhome-{area}", "myhome", f"https://www.myhome.ie/residential/{area}/house-for-sale"))
    return out


# --- page parsing ------------------------------------------------------------

def _daft_listing(item: dict) -> Listing | None:
    path = item.get("seoFriendlyPath")
    if not path:
        return None
    hit = classify("https://www.daft.ie" + path)
    if not hit:
        return None
    l = Listing(url=hit[1], source="daft", address=item.get("title") or "")
    l.price = parse_price(item.get("price") or item.get("abbreviatedPrice"))
    for attr, key in (("bedrooms", "numBedrooms"), ("bathrooms", "numBathrooms")):
        m = re.search(r"\d", str(item.get(key) or ""))
        setattr(l, attr, int(m.group(0)) if m else None)
    l.property_type = normalise_type(item.get("propertyType"))
    rating = str((item.get("ber") or {}).get("rating") or "").upper()
    l.ber = rating if rating in BER_ORDER else None
    seller = item.get("seller") or {}
    l.agent_name = seller.get("name") or seller.get("branch")
    l.agent_phone = seller.get("phone")
    images = (item.get("media") or {}).get("images") or []
    if images and isinstance(images[0], dict):
        l.image = next((images[0][k] for k in ("size720x480", "size600x600", "size1200x1200") if images[0].get(k)), None)
    label = json.dumps({k: item.get(k) for k in ("label", "stamp", "saleType", "state")}).lower()
    l.sale_agreed = "sale agreed" in label
    l.new_build = "new-home" in l.url or bool(item.get("prs"))
    return l


def _daft_next_data(html: str) -> list[Listing] | None:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        props = json.loads(m.group(1))["props"]["pageProps"]
    except (json.JSONDecodeError, KeyError):
        return None
    items = props.get("listings")
    if not isinstance(items, list):
        return None
    out = []
    for entry in items:
        item = entry.get("listing", entry) if isinstance(entry, dict) else None
        l = _daft_listing(item) if isinstance(item, dict) else None
        if l:
            out.append(l)
    return out


BASE = {"daft": "https://www.daft.ie", "myhome": "https://www.myhome.ie"}


def _listing_urls(tag, base: str) -> set[str]:
    urls = set()
    for a in tag.find_all("a", href=True):
        href = a["href"]
        hit = classify(base + href if href.startswith("/") else href)
        if hit:
            urls.add(hit[1])
    return urls


def _cards(html: str, source: str) -> list[Listing]:
    """Fallback: find listing links and read the text of the card around each one."""
    base = BASE.get(source, "")
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Listing] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        hit = classify(base + href if href.startswith("/") else href)
        if not hit or hit[1] in found:
            continue
        # Climb to the largest element that still holds only this one listing.
        card = a
        while card.parent is not None and card.parent.name not in ("body", "html", "[document]"):
            parent = card.parent
            if len(_listing_urls(parent, base)) > 1 or len(parent.get_text(" ", strip=True)) > 1500:
                break
            card = parent
        text = card.get_text(" ", strip=True)
        l = Listing(url=hit[1], source=hit[0])
        l.price = parse_price(text)
        m = BEDS_RE.search(text)
        l.bedrooms = int(m.group(1)) if m else None
        m = BATHS_RE.search(text)
        l.bathrooms = int(m.group(1)) if m else None
        m = BER_IN_CARD.search(text)
        if not m:
            img = card.find("img", alt=re.compile(r"BER", re.I))
            m = BER_VALUE.search(img["alt"]) if img else None
        l.ber = m.group(1).upper() if m else None
        l.property_type = normalise_type(text)
        l.sale_agreed = bool(re.search(r"\bsale agreed\b", text, re.I))
        l.new_build = "new-home" in l.url or bool(re.search(r"\bnew (?:home|build|development)\b", text, re.I))
        found[hit[1]] = l
    return list(found.values())


BER_VALUE = re.compile(r"\b(A1|A2|A3|B1|B2|B3|C1|C2|C3|D1|D2|E1|E2|F|G)\b", re.I)
BER_IN_CARD = re.compile(r"\bBER\s*:?\s*(A1|A2|A3|B1|B2|B3|C1|C2|C3|D1|D2|E1|E2|F|G)\b", re.I)


def parse_search_page(html: str, source: str) -> list[Listing]:
    if source == "daft":
        listings = _daft_next_data(html)
        if listings:
            return listings
    return _cards(html, source)


# --- running a sweep ---------------------------------------------------------

def run_searches(searches: list[Search], http: requests.Session, max_pages: int = MAX_PAGES_PER_SEARCH,
                 debug_dir: Path | None = None) -> tuple[list[Listing], dict]:
    """Fetch every page of every search. Returns listings (deduplicated) and per-search stats."""
    listings: dict[str, Listing] = {}
    stats: dict[str, dict] = {}
    first = True
    for s in searches:
        st = stats[s.name] = {"pages": 0, "listings": 0, "error": None}
        for page in range(1, max_pages + 1):
            if not first:
                time.sleep(PAGE_DELAY_SECONDS)
            first = False
            url = s.page_url(page)
            try:
                r = http.get(url, timeout=25)
            except requests.RequestException as e:
                st["error"] = str(e)[:200]
                break
            if r.status_code != 200:
                st["error"] = f"HTTP {r.status_code}"
                break
            found = parse_search_page(r.text, s.source)
            if debug_dir and page == 1 and not found:
                # Keep a copy of pages we could not read, so the parser can be fixed.
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"{s.name}.html").write_text(r.text[:600_000], encoding="utf-8")
            new = [l for l in found if l.url not in listings]
            st["pages"] += 1
            st["listings"] += len(new)
            for l in new:
                listings[l.url] = l
            if not new:
                break
    for name, st in stats.items():
        log.info("search %s: %d page(s), %d listing(s)%s", name, st["pages"], st["listings"],
                 f", error {st['error']}" if st["error"] else "")
    return list(listings.values()), stats
