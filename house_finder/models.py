from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

BER_ORDER = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3",
             "D1", "D2", "E1", "E2", "F", "G"]


def ber_rank(rating: str | None) -> int | None:
    """Lower is better. None when unknown or exempt."""
    if not rating:
        return None
    rating = rating.upper().strip()
    return BER_ORDER.index(rating) if rating in BER_ORDER else None


@dataclass
class Listing:
    url: str
    source: str
    address: str = ""
    price: int | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    property_type: str | None = None   # normalised, see parse.normalise_type
    ber: str | None = None
    description: str = ""
    sale_agreed: bool = False
    new_build: bool = False
    parking: int | None = None          # number of spaces, if stated
    floor_area_m2: float | None = None
    image: str | None = None
    agent_name: str | None = None
    agent_phone: str | None = None
    agent_email: str | None = None
    viewings: list[str] = field(default_factory=list)
    details_fetched: bool = False

    @property
    def id(self) -> str:
        return hashlib.sha1(self.url.encode()).hexdigest()[:10]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Listing":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)
