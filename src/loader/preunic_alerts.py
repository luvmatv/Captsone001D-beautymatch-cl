"""Alerts that keep Preunic's load from deactivating listings even when every category matches its total.

The page total is the only check of a Preunic listing, and the store sets it:
on 2026-10-14 /t/perfumes-y-fragancias said 77 (it had 479) because the
catalog moved to /t/perfume. The 25 % deactivation limit stopped that one, but
a drop to, say, 380 (-21 %) would have passed and deactivated 99 listings.

An alert leaves the store partial and deactivates nothing; the prices are
loaded anyway. Two alerts:

1. A total drops by more than DROP_SHARE against the last accepted whole
   listing: the store's distinct listings, and each category's page total
   when the store's total drops too (a category that shrinks while the store
   holds was reorganized: on 2026-10-14 the 479 of /t/perfumes-y-fragancias
   became 77 + 405 in /t/perfume). A category with no history never alerts.
   A lower total that holds ACCEPT_AFTER runs in a row (each within
   STREAK_TOLERANCE of the first lower total: the site's totals move a little
   most days) becomes the new baseline (a real catalog change), and the note
   says so. On the run that accepts the store's drop (and the next two, while
   the total stays near it), its deactivation limit rises to the accepted drop
   plus ACCEPTED_LIMIT_MARGIN, so the listings that left are deactivated once
   instead of being held by the 25 % limit forever
   (2026-11-18: the Christmas sets left /t/perfume, 501 -> 358, -29 %).
2. More than NEW_SHARE of the listings read are new to the store (a change in
   its URLs would make every listing look new).

The history is the store's earlier scrape files in the same folder (the
production copy keeps them all): only finished, whole listings count, and the
outcome is recomputed from them each time, so no state is stored anywhere.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DROP_SHARE = 0.10
ACCEPT_AFTER = 3
STREAK_TOLERANCE = 0.03       # a run at 280 or 283 continues a streak that started at 281
ACCEPTED_LIMIT_MARGIN = 0.03  # deactivation limit on the accepting run: the store's drop + 3 points
NEW_SHARE = 0.10
HISTORY_FILES = 60  # the store's latest scrape files read for the baseline
STORE = "store"     # key of the store-level total, next to the category URLs


def listing_totals(data: dict[str, Any]) -> dict[str, int] | None:
    """{category URL: its page total, STORE: distinct listings} of a finished, whole listing; else None."""
    if (data.get("progress") or {}).get("step") != "done":
        return None
    pagination = data.get("pagination") or {}
    categories = pagination.get("categories")
    if categories is None:  # one category, before 2026-10-15
        total = pagination.get("site_total")
        distinct = len({product.get("url") for product in data.get("products") or [] if product.get("url")})
        if total is None or pagination.get("listing_complete") is False or distinct != total:
            return None
        return {(data.get("category_url") or "?").rstrip("/"): total, STORE: distinct}
    if not categories or not all(category.get("listing_complete") is True and not category.get("error")
                                 for category in categories):
        return None
    totals = {category["category_url"].rstrip("/"): category["site_total"] for category in categories}
    totals[STORE] = pagination.get("urls_distinct")
    return totals


def label(key: str) -> str:
    return "store" if key == STORE else f"category {urlsplit(key).path or key}"


def drop_review(history: list[dict[str, int]]) -> tuple[list[str], list[str], float | None]:
    """(alerts, notes, accepted store drop) for the last listing of the history (oldest first).

    A total that falls by more than DROP_SHARE against its baseline alerts; a
    rise or a small change becomes the new baseline. A lower total that holds
    ACCEPT_AFTER listings in a row (each within STREAK_TOLERANCE of the first
    lower total) becomes the baseline, with a note. When that happened to the
    store's total on the last listing, or on one of the ACCEPT_AFTER - 1
    listings before it with the total still near the accepted one, the store's
    accepted drop share is returned (else None).
    A category with no baseline (new) never alerts, and a category that drops
    while the store's total holds is a reorganization (its listings moved to
    another category): its new total becomes the baseline at once, with a note.
    """
    baseline: dict[str, int] = {}
    streak: dict[str, tuple[int, int]] = {}  # key -> (first lower total, listings in a row near it)
    alerts: list[str] = []
    notes: list[str] = []
    accepted: float | None = None
    recent: tuple[float, int, int] | None = None  # (accepted store drop, total accepted, runs since)
    for totals in history:
        alerts, notes, accepted = [], [], None
        store_base = baseline.get(STORE)
        store_holds = store_base is None or totals.get(STORE, 0) >= store_base * (1 - DROP_SHARE)
        for key, total in totals.items():
            base = baseline.get(key)
            if base is None or total >= base * (1 - DROP_SHARE):
                baseline[key] = total
                streak.pop(key, None)
                continue
            if key != STORE and store_holds:
                baseline[key] = total
                streak.pop(key, None)
                notes.append(f"{label(key)}: total {base} -> {total} while the store's total holds "
                             f"({store_base} -> {totals.get(STORE)}): a reorganization, new baseline")
                continue
            first, count = streak.get(key, (None, 0))
            if first is not None and abs(total - first) <= first * STREAK_TOLERANCE:
                count += 1
            else:
                first, count = total, 1
            if count >= ACCEPT_AFTER:
                baseline[key] = total
                streak.pop(key, None)
                near = "at it" if total == first else f"near it (first {first})"
                notes.append(f"{label(key)}: total {total} accepted as the new baseline after {ACCEPT_AFTER} "
                             f"runs in a row {near} (was {base})")
                if key == STORE:
                    accepted = (base - total) / base
            else:
                streak[key] = (first, count)
                alerts.append(f"ALERT: {label(key)} total dropped from {base} to {total} ({(total - base) / base:.0%}, "
                              f"more than {DROP_SHARE:.0%}; run {count} of {ACCEPT_AFTER} at this total): "
                              f"nothing deactivated")
        # The raised limit holds on the accepting run and the next ACCEPT_AFTER - 1 runs while the store's
        # total stays near the accepted one: if that day's load was held back (another alert, or this code
        # arrived a day late), the listings that left are still deactivated once.
        store_total = totals.get(STORE)
        if accepted is not None:
            recent = (accepted, store_total, 0)
        elif recent is not None:
            share, anchor, age = recent
            age += 1
            if store_total is not None and age < ACCEPT_AFTER and abs(store_total - anchor) <= anchor * STREAK_TOLERANCE:
                recent, accepted = (share, anchor, age), share
            else:
                recent = None
    return alerts, notes, accepted


def drop_alerts(history: list[dict[str, int]]) -> tuple[list[str], list[str]]:
    """(alerts, notes) of drop_review."""
    alerts, notes, _ = drop_review(history)
    return alerts, notes


def earlier_totals(directory: Path, store: str, before: datetime) -> list[dict[str, int]]:
    """Totals of the store's whole listings scraped before `before`, oldest first."""
    found = []
    for path in sorted(directory.glob(f"{store}_*.json"))[-HISTORY_FILES:]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scraped_at = datetime.fromisoformat(data["scraped_at"])
        except (OSError, ValueError, KeyError):
            continue
        totals = listing_totals(data)
        if totals and scraped_at < before:
            found.append((scraped_at, totals))
    return [totals for _, totals in sorted(found, key=lambda pair: pair[0])]


def new_listing_alert(known_in_store: int, known_read: int, read: int) -> list[str]:
    """Alert when more than NEW_SHARE of the listings read are new to a store that already has listings."""
    new = read - known_read
    if known_in_store and read and new / read > NEW_SHARE:
        return [f"ALERT: {new} of {read} listings read are new to the store ({new / read:.0%}, more than "
                f"{NEW_SHARE:.0%}; did its URLs change?): nothing deactivated"]
    return []


def preunic_alerts(cursor, store_id: int, data: dict[str, Any], urls: list[str], path: Path,
                   scraped_at: datetime) -> tuple[list[str], list[str], float | None]:
    """(alerts, notes, deactivation limit) of a Preunic scrape file being loaded (before its listings are written).

    The limit is None, or the accepted store drop plus ACCEPTED_LIMIT_MARGIN on the run that accepts it.
    """
    known_in_store = cursor.execute("SELECT count(*) FROM raw_listings WHERE store_id = %s",
                                    (store_id,)).fetchone()[0]
    known_read = cursor.execute("SELECT count(*) FROM raw_listings WHERE store_id = %s AND listing_url = ANY(%s)",
                                (store_id, urls)).fetchone()[0]
    alerts = new_listing_alert(known_in_store, known_read, len(urls))
    notes: list[str] = []
    limit = None
    totals = listing_totals(data)
    if totals:  # a listing that is not whole is already partial
        drops, notes, accepted = drop_review(earlier_totals(path.parent, data["store"], scraped_at) + [totals])
        alerts += drops
        if accepted is not None:
            limit = accepted + ACCEPTED_LIMIT_MARGIN
    return alerts, notes, limit
