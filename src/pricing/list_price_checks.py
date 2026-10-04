"""Checks of the list price ("precio normal" tachado) a store shows next to a discount.

Two checks, each on one current offer (a listing's latest reading):

1. Against the listing's own history (the main check): is the list price
   higher than the highest price the same listing charged without a discount
   within the last window_days? A store whose "normal" price is above every
   undiscounted price it actually charged contradicts its own history.
2. Against the market (context only, not an alert): is the list price more
   than MARKET_MARGIN above what the other stores charge without a discount
   for the same matched product? It depends on the matching and on another
   store selling it undiscounted.

Neither check claims intent: they say what the readings show. With no
reading to compare against, the answer is "insufficient data", never "fine".
A third check (a list price never charged over a long window) waits for a
month of history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from statistics import median

DEFAULT_WINDOW_DAYS = 30
# Exploration of 2026-10-03 (against the highest undiscounted price of the
# other stores): no list price of Maicao or Salcobrand was more than 20 %
# above it, 2 of Preunic's and 22 of Beauty Perfumes' were.
MARKET_MARGIN = 0.20


class HistoryStatus(StrEnum):
    NO_LIST_PRICE = "no_list_price"          # no discount shown: nothing to check
    INSUFFICIENT_DATA = "insufficient_data"  # no undiscounted reading in the window
    CONSISTENT = "consistent"                # list price <= highest undiscounted price
    ABOVE_HISTORY = "above_history"          # list price > highest undiscounted price


class MarketStatus(StrEnum):
    NO_LIST_PRICE = "no_list_price"
    INSUFFICIENT_DATA = "insufficient_data"  # no other store sells it available and undiscounted
    WITHIN_MARKET = "within_market"
    ABOVE_MARKET = "above_market"            # list price > reference x (1 + MARKET_MARGIN)


@dataclass(frozen=True)
class Reading:
    """One price_history row of a listing."""

    scraped_at: datetime
    price: int
    list_price: int | None
    is_available: bool

    @property
    def discounted(self) -> bool:
        return self.list_price is not None and self.list_price > self.price


@dataclass(frozen=True)
class Offer:
    """A listing's current reading, with all its readings (any order)."""

    store: str
    listing_url: str
    current: Reading
    history: tuple[Reading, ...]


@dataclass(frozen=True)
class HistoryCheck:
    status: HistoryStatus
    reference_price: int | None           # highest price charged without a discount in the window
    reference_scraped_at: datetime | None  # the latest reading at that price
    observed_from: datetime | None        # first reading in the window
    points_in_window: int
    undiscounted_points: int


@dataclass(frozen=True)
class MarketCheck:
    status: MarketStatus
    reference_price: int | None   # median over the other stores of their lowest undiscounted price
    reference_stores: tuple[str, ...]
    percent_above: float | None   # (list price - reference) / reference, in percent


def check_history(offer: Offer, window_days: int = DEFAULT_WINDOW_DAYS) -> HistoryCheck:
    """Check 1 over the readings of the window_days before the current reading (both ends included).

    Readings without stock are not a reference: that price could not be paid.
    """
    end = offer.current.scraped_at
    window = [r for r in offer.history if end - timedelta(days=window_days) <= r.scraped_at <= end]
    undiscounted = [r for r in window if not r.discounted and r.is_available]
    observed_from = min((r.scraped_at for r in window), default=None)
    counts = {"observed_from": observed_from, "points_in_window": len(window), "undiscounted_points": len(undiscounted)}
    if not offer.current.discounted:
        return HistoryCheck(HistoryStatus.NO_LIST_PRICE, None, None, **counts)
    if not undiscounted:
        return HistoryCheck(HistoryStatus.INSUFFICIENT_DATA, None, None, **counts)
    reference = max(undiscounted, key=lambda r: (r.price, r.scraped_at))
    status = HistoryStatus.ABOVE_HISTORY if offer.current.list_price > reference.price else HistoryStatus.CONSISTENT
    return HistoryCheck(status, reference.price, reference.scraped_at, **counts)


def check_market(offer: Offer, others: list[Offer]) -> MarketCheck:
    """Check 2 against the other stores' current offers of the same product.

    Each other store counts once, with its lowest available undiscounted price
    (what a shopper pays there; a store that lists the product twice does not
    weigh double). The reference is the median of those prices, so a single
    expensive store does not move it.
    """
    if not offer.current.discounted:
        return MarketCheck(MarketStatus.NO_LIST_PRICE, None, (), None)
    by_store: dict[str, int] = {}
    for other in others:
        reading = other.current
        if other.store == offer.store or reading.discounted or not reading.is_available:
            continue
        by_store[other.store] = min(reading.price, by_store.get(other.store, reading.price))
    if not by_store:
        return MarketCheck(MarketStatus.INSUFFICIENT_DATA, None, (), None)
    reference = round(median(by_store.values()))
    percent = round(100 * (offer.current.list_price - reference) / reference, 1)
    status = (MarketStatus.ABOVE_MARKET if offer.current.list_price > reference * (1 + MARKET_MARGIN)
              else MarketStatus.WITHIN_MARKET)
    return MarketCheck(status, reference, tuple(sorted(by_store)), percent)


def check_offers(offers: list[Offer], window_days: int = DEFAULT_WINDOW_DAYS) -> list[tuple[Offer, HistoryCheck, MarketCheck]]:
    """Both checks for every current offer of one product."""
    return [(offer, check_history(offer, window_days), check_market(offer, offers)) for offer in offers]
