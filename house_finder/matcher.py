"""Decide whether a listing fits the preferences, and how well."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .models import Listing, ber_rank

# Adjective, then up to two other words, then "garden": "large mature rear garden".
_G = r"(?:[\w-]+\s+){0,2}gardens?"
GARDEN_GOOD = {
    r"south[- ]facing\s+" + _G: 3, r"(?:south[- ])?west[- ]facing\s+" + _G: 2,
    r"(?:large|generous|substantial|extensive|spacious|big)\s+" + _G: 3,
    r"(?:mature|landscaped|private|walled)\s+" + _G: 2,
    r"not overlooked": 2, r"secluded": 2, r"sun[- ]drenched": 1, r"\bpatio\b": 1, r"\blawn\b": 1,
    r"\bdecking\b": 1, r"garden room": 1, r"corner site": 2, r"large site": 3, r"\bacres?\b": 3,
    r"side (?:entrance|access)": 1, r"greenhouse": 2,
}
GARDEN_BAD = {r"communal\s+" + _G: -2, r"\bcourtyard\b": -1, r"\bno garden": -4,
              r"low[- ]maintenance\s+" + _G: -1}


@dataclass
class Verdict:
    ok: bool
    score: int = 0
    reasons: list[str] = field(default_factory=list)   # why it was rejected
    notes: list[str] = field(default_factory=list)     # highlights / warnings for the message
    htb: bool = False


def _fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def matches_area(address: str, areas: list[str]) -> str | None:
    if not areas:
        return "any"
    addr = _fold(address)
    for a in areas:
        fa = _fold(a)
        if re.search(r"\b" + re.escape(fa) + r"\b(?!\d)", addr):
            return a
        # "Dublin 18" is often written "D18"
        m = re.fullmatch(r"dublin (\d+w?)", fa)
        if m and re.search(r"\bd" + m.group(1) + r"\b", addr):
            return a
    return None


def garden_score(text: str) -> int:
    t = text.lower()
    score = sum(v for k, v in {**GARDEN_GOOD, **GARDEN_BAD}.items() if re.search(k, t))
    m = re.search(r"garden[^.]{0,40}?(\d{2,3})\s*(?:ft|feet|m\b|metres|meters)", t)
    if m:
        length = int(m.group(1))
        is_ft = "ft" in m.group(0) or "feet" in m.group(0)
        metres = length * 0.3048 if is_ft else length
        score += 3 if metres >= 20 else 2 if metres >= 12 else 0
    return score


def evaluate(listing: Listing, prefs: dict) -> Verdict:
    v = Verdict(ok=True)
    budget = prefs.get("budget", {})
    types: list[str] = prefs.get("property_types", [])
    beds = prefs.get("bedrooms", {})
    baths = prefs.get("bathrooms", {})

    def reject(reason: str):
        v.ok = False
        v.reasons.append(reason)

    if listing.sale_agreed and prefs.get("exclude_sale_agreed", True):
        reject("sale agreed")

    if listing.price is not None and listing.price > budget.get("max", 10**9):
        reject(f"price {listing.price} over budget")

    area = matches_area(listing.address, prefs.get("areas") or [])
    if area is None:
        reject("area not in list")
    avoid = prefs.get("avoid_areas") or []
    bad = matches_area(listing.address, avoid) if avoid else None
    if bad:
        reject(f"avoided area {bad}")

    ptype = listing.property_type
    if ptype and types and ptype not in types:
        reject(f"type {ptype} not wanted")
    if ptype == "apartment":
        if listing.bedrooms is not None and listing.bedrooms < prefs.get("apartment_min_bedrooms", 2):
            reject("apartment too small")
        if listing.price and listing.price > prefs.get("apartment_max_price", budget.get("max", 10**9)):
            reject("apartment over apartment budget")

    if listing.bedrooms is not None:
        if listing.bedrooms < beds.get("min", 0):
            reject(f"{listing.bedrooms} bedrooms")
        if beds.get("max") and listing.bedrooms > beds["max"]:
            reject(f"{listing.bedrooms} bedrooms (too many)")
    if listing.bathrooms is not None and listing.bathrooms < baths.get("min", 0):
        reject(f"{listing.bathrooms} bathrooms")

    br, min_br = ber_rank(listing.ber), ber_rank(prefs.get("min_ber"))
    if br is not None and min_br is not None and br > min_br:
        reject(f"BER {listing.ber}")

    if listing.parking is not None and listing.parking < prefs.get("parking_min", 0):
        reject("not enough parking")

    if not v.ok:
        return v

    # Scoring: higher is better. Roughly 0-30.
    if ptype in types:
        v.score += max(0, 6 - 2 * types.index(ptype))
    if listing.bedrooms is not None:
        v.score += 4 if listing.bedrooms == beds.get("ideal") else 2
    if listing.bathrooms is not None:
        v.score += 3 if listing.bathrooms >= baths.get("ideal", 99) else 1
    if br is not None:
        v.score += max(0, 5 - br)          # A1 = 5 ... B2 = 1
    if listing.parking:
        v.score += min(listing.parking, 3)
    if listing.new_build and prefs.get("prefer_new_build"):
        v.score += 3
    g = garden_score(listing.description)
    v.score += max(-3, min(g, 8))
    if g >= 4:
        v.notes.append("🌳 حیاط بزرگ/خوب")
    elif g <= -1:
        v.notes.append("⚠️ احتمالاً حیاط کوچک یا مشترک")

    if listing.new_build and listing.price and listing.price <= budget.get("htb_max", 500000):
        v.htb = True
        v.notes.append("💶 احتمالاً واجد Help to Buy")

    unknown = [name for name, val in (("BER", listing.ber), ("تعداد حمام", listing.bathrooms),
                                      ("پارکینگ", listing.parking), ("قیمت", listing.price)) if val is None]
    if unknown:
        v.notes.append("❔ نامشخص: " + "، ".join(unknown))
    return v
