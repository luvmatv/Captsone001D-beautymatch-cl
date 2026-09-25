from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.matching.normalization import expand_abbreviations
from src.scrapers.concentration import extract_concentration
from src.scrapers.volume import extract_volume

# Scraper values -> database concentration_type enum.
CONCENTRATIONS = {
    "EDP": "edp",
    "EDT": "edt",
    "EDC": "cologne",
    "PARFUM": "parfum",
}

# CLP amounts: "$19.990" (dot = thousands separator), "$999". No decimals.
PRICE_PATTERN = re.compile(r"^\$\s?(\d{1,3}(?:\.\d{3})+|\d+)$")
VOLUME_PATTERN = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(ml|cc|l|lts?|litros?)$", re.IGNORECASE)
LITRE_UNITS = {"l", "lt", "lts", "litro", "litros"}
MAICAO_SKU_PATTERN = re.compile(r"(CLMC_\d+)")


@dataclass(frozen=True)
class Listing:
    listing_url: str
    store_sku: str | None
    raw_name: str
    raw_brand: str | None
    parsed_concentration: str | None
    parsed_volume_ml: int | None
    price: Decimal | None
    list_price: Decimal | None
    is_available: bool


def to_concentration(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return CONCENTRATIONS[value.upper()]
    except KeyError:
        raise ValueError(f"unknown scraper concentration {value!r}") from None


def to_price(value: str | None) -> Decimal | None:
    if not value:
        return None
    match = PRICE_PATTERN.match(value.strip())
    if not match:
        raise ValueError(f"unrecognized price {value!r}")
    return Decimal(match.group(1).replace(".", ""))


def to_volume_ml(value: str | None) -> int | None:
    """"200 mL" -> 200, "1,5 L" -> 1500, "1Lt" -> 1000, "120cc" -> 120.
    Unit counts such as "3 un" -> None."""
    if not value:
        return None
    match = VOLUME_PATTERN.match(value.strip())
    if not match:
        return None
    number, unit = match.groups()
    unit = unit.lower()
    if unit in {"ml", "cc"} and re.fullmatch(r"\d{1,3}\.\d{3}", number):
        number = number.replace(".", "")  # "1.000 ml" uses a thousands separator
    amount = Decimal(number.replace(",", "."))
    if unit in LITRE_UNITS:
        amount *= 1000
    volume_ml = int(amount.to_integral_value(rounding=ROUND_HALF_UP))
    return volume_ml if volume_ml > 0 else None


def normalize_url(url: str) -> str:
    """Drop query string and fragment (Maicao appends ?cgid=<category>)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def store_sku(store: str, url: str) -> str | None:
    if store == "maicao":
        match = MAICAO_SKU_PATTERN.search(url)
        return match.group(1) if match else None
    return None  # Preunic listings do not expose the SKU


def listing_from_product(store: str, product: dict[str, Any]) -> Listing:
    url = normalize_url(product["url"])
    return Listing(
        listing_url=url,
        store_sku=store_sku(store, url),
        raw_name=product["name"].strip(),
        raw_brand=(product.get("brand") or "").strip() or None,
        # Scrapes made before a pattern was added (e.g. "colonia") still get it.
        parsed_concentration=to_concentration(
            product.get("concentration") or extract_concentration(product["name"])
        ),
        # Same fallback for sizes the scraper missed ("X30Ml", "SP100M").
        parsed_volume_ml=to_volume_ml(
            product.get("volume") or extract_volume(expand_abbreviations(product["name"]))
        ),
        price=to_price(product.get("current_price")),
        list_price=to_price(product.get("previous_price")),
        is_available=product.get("availability") != "Sin stock online",
    )
