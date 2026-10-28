"""Pull listing details out of a listing page.

Each site embeds structured data differently, so we try, in order:
1. Daft's Next.js page data (__NEXT_DATA__)
2. schema.org JSON-LD blocks (MyHome, Property.ie, many agent sites)
3. Plain-text patterns over the visible page text
Whatever a step finds is kept; later steps only fill gaps.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .models import BER_ORDER, Listing

TYPE_WORDS = [
    ("semi-detached", ("semi-detached", "semi detached", "semi-d")),
    ("end-of-terrace", ("end of terrace", "end-of-terrace", "end terrace")),
    ("terraced", ("terrace", "townhouse", "mid-terrace", "mews")),
    ("detached", ("detached", "bungalow", "dormer")),
    ("apartment", ("apartment", "duplex", "flat", "penthouse")),
]

BER_RE = re.compile(r"\bBER(?:\s*(?:rating|cert(?:ificate)?))?\s*[:\-]?\s*(A1|A2|A3|B1|B2|B3|C1|C2|C3|D1|D2|E1|E2|F|G)\b", re.I)
BEDS_RE = re.compile(r"\b(\d)\s*(?:-\s*)?(?:bed(?:room)?s?)\b", re.I)
BATHS_RE = re.compile(r"\b(\d)\s*(?:-\s*)?(?:bath(?:room)?s?)\b", re.I)
PRICE_RE = re.compile(r"€\s?(\d{1,3}(?:,\d{3})+|\d{5,7})")
AREA_RE = re.compile(r"(\d{2,4}(?:\.\d+)?)\s*(m²|m2|sq\.?\s?m|sqm|sq\.?\s?ft|ft²)", re.I)
PARKING_RE = re.compile(r"(?:parking|driveway|garage|off[- ]street)[^.]{0,60}?\b(\d|one|two|three|four)\b[^.]{0,20}?(?:car|space|vehicle)", re.I)
PARKING_RE2 = re.compile(r"\b(\d|one|two|three|four)\s*(?:car|cars|parking spaces?|spaces)\b", re.I)
VIEWING_RE = re.compile(r"[^.\n]*\b(?:viewing|viewings|open (?:day|viewing)|view(?:ing)? by appointment|on view)\b[^.\n]*", re.I)
WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4}


def normalise_type(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    for name, words in TYPE_WORDS:
        if any(w in t for w in words):
            return name
    if "house" in t:
        return "detached" if "detached" in t else None
    return None


def parse_price(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 10000 else None
    m = PRICE_RE.search(str(value)) or re.search(r"(\d{5,7})", str(value).replace(",", ""))
    if not m:
        return None
    return int(m.group(1).replace(",", ""))


def _first_int(regex: re.Pattern, text: str) -> int | None:
    m = regex.search(text or "")
    return int(m.group(1)) if m else None


def _dig(obj, *keys):
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        elif isinstance(obj, list) and isinstance(k, int) and len(obj) > k:
            obj = obj[k]
        else:
            return None
    return obj


def _apply_daft(listing: Listing, soup: BeautifulSoup) -> None:
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag or not tag.string:
        return
    try:
        data = json.loads(tag.string)
    except json.JSONDecodeError:
        return
    item = _dig(data, "props", "pageProps", "listing") or {}
    if not item:
        return
    listing.address = listing.address or item.get("title") or ""
    listing.price = listing.price or parse_price(item.get("price"))
    listing.bedrooms = listing.bedrooms or _first_int(re.compile(r"(\d)"), str(item.get("numBedrooms") or ""))
    listing.bathrooms = listing.bathrooms or _first_int(re.compile(r"(\d)"), str(item.get("numBathrooms") or ""))
    listing.property_type = listing.property_type or normalise_type(item.get("propertyType"))
    rating = _dig(item, "ber", "rating")
    if rating and str(rating).upper() in BER_ORDER:
        listing.ber = str(rating).upper()
    seller = item.get("seller") or {}
    listing.agent_name = listing.agent_name or seller.get("name") or seller.get("branch")
    listing.agent_phone = listing.agent_phone or seller.get("phone") or seller.get("phoneWhenToCall")
    listing.agent_email = listing.agent_email or seller.get("email")
    images = _dig(item, "media", "images") or []
    if images and isinstance(images[0], dict):
        img = images[0]
        listing.image = listing.image or next((img[k] for k in ("size720x480", "size600x600", "size1200x1200") if img.get(k)), None)
    desc = _dig(data, "props", "pageProps", "listingDetails", "description") or item.get("description") or ""
    listing.description = listing.description or str(desc)
    label = " ".join(str(item.get(k) or "") for k in ("label", "saleType", "state", "stamp"))
    if "sale agreed" in label.lower() or "sold" in label.lower().split():
        listing.sale_agreed = True
    if item.get("newHome") or "new-home" in listing.url or item.get("prs") or item.get("category") == "New Homes":
        listing.new_build = True
    if "floorArea" in item:
        listing.floor_area_m2 = listing.floor_area_m2 or _area_to_m2(_dig(item, "floorArea", "value"), _dig(item, "floorArea", "unit"))


def _area_to_m2(value, unit) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    unit = str(unit or "").lower()
    return round(v * 0.092903, 1) if "ft" in unit else v


def _apply_jsonld(listing: Listing, soup: BeautifulSoup) -> None:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []:
            if not isinstance(node, dict):
                continue
            offers = node.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            listing.price = listing.price or parse_price(offers.get("price") or offers.get("lowPrice"))
            addr = node.get("address")
            if isinstance(addr, dict):
                addr = ", ".join(str(addr[k]) for k in ("streetAddress", "addressLocality", "addressRegion") if addr.get(k))
            if addr and not listing.address:
                listing.address = str(addr)
            listing.address = listing.address or node.get("name") or ""
            listing.bedrooms = listing.bedrooms or _int(node.get("numberOfBedrooms") or node.get("numberOfRooms"))
            listing.bathrooms = listing.bathrooms or _int(node.get("numberOfBathroomsTotal"))
            listing.description = listing.description or str(node.get("description") or "")
            img = node.get("image")
            if isinstance(img, list):
                img = img[0] if img else None
            if isinstance(img, dict):
                img = img.get("url")
            listing.image = listing.image or img


def _int(v) -> int | None:
    try:
        return int(str(v).strip()[:2])
    except (TypeError, ValueError):
        return None


def _apply_text(listing: Listing, text: str) -> None:
    listing.ber = listing.ber or (m.group(1).upper() if (m := BER_RE.search(text)) else None)
    listing.bedrooms = listing.bedrooms or _first_int(BEDS_RE, text)
    listing.bathrooms = listing.bathrooms or _first_int(BATHS_RE, text)
    listing.price = listing.price or parse_price(text)
    listing.property_type = listing.property_type or normalise_type(text[:3000])
    low = text.lower()
    if re.search(r"\bsale agreed\b", low[:4000]):
        listing.sale_agreed = True
    if re.search(r"\b(new build|new home|new development|brand new|show house|newly built)\b", low):
        listing.new_build = True
    if listing.parking is None:
        m = PARKING_RE.search(text) or PARKING_RE2.search(text)
        if m:
            g = m.group(1).lower()
            listing.parking = WORDNUM.get(g) or int(g)
        elif re.search(r"\b(driveway|off[- ]street parking|garage|designated parking|parking space)\b", low):
            listing.parking = 1
    if listing.floor_area_m2 is None and (m := AREA_RE.search(text)):
        listing.floor_area_m2 = _area_to_m2(m.group(1), m.group(2))
    if not listing.viewings:
        seen = set()
        for m in VIEWING_RE.finditer(text):
            line = " ".join(m.group(0).split())[:200]
            if 12 < len(line) and line.lower() not in seen:
                seen.add(line.lower())
                listing.viewings.append(line)
            if len(listing.viewings) >= 3:
                break
    if not listing.agent_phone:
        m = re.search(r"(?:\+353\s?|\b0)(?:1|[2-9]\d)\s?\d{3}\s?\d{3,4}\b", text)
        listing.agent_phone = m.group(0) if m else None
    if not listing.agent_email:
        m = re.search(r"[\w.+-]+@[\w-]+\.(?:ie|com|net)\b", text)
        if m and not any(s in m.group(0) for s in ("daft.ie", "myhome.ie", "property.ie", "example")):
            listing.agent_email = m.group(0)


def parse_listing_page(listing: Listing, html: str) -> Listing:
    soup = BeautifulSoup(html, "html.parser")
    if listing.source == "daft":
        _apply_daft(listing, soup)
    _apply_jsonld(listing, soup)
    if not listing.image:
        og = soup.find("meta", property="og:image")
        listing.image = og.get("content") if og else None
    if not listing.address:
        og = soup.find("meta", property="og:title")
        listing.address = (og.get("content") if og else None) or (soup.title.string.strip() if soup.title and soup.title.string else "")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    text = soup.get_text(" ", strip=True)
    _apply_text(listing, (listing.description + " " + text))
    listing.details_fetched = True
    return listing
