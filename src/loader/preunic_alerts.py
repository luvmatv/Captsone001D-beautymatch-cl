"""Alerts that keep Preunic's load from deactivating listings even when every category matches its total.

The page total is the only check of a Preunic listing, and the store sets it:
on 2026-10-14 /t/perfumes-y-fragancias said 77 (it had 479) because the
catalog moved to /t/perfume. The 25 % deactivation limit stopped that one, but
a drop to, say, 380 (-21 %) would have passed and deactivated 99 listings.

An alert leaves the store partial and deactivates nothing; the prices are
loaded anyway. Two alerts:

1. A total drops by more than DROP_SHARE against the last accepted whole
   listing: each category's page total, and the store's distinct listings.
   The same lower total ACCEPT_AFTER runs in a row becomes the new baseline
   (a real catalog change), and the note says so.
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


def drop_alerts(history: list[dict[str, int]]) -> tuple[list[str], list[str]]:
    """(alerts, notes) for the last listing of the history (oldest first).

    A total that falls by more than DROP_SHARE against its baseline alerts; a
    rise or a small change becomes the new baseline. The same lower total
    ACCEPT_AFTER listings in a row becomes the baseline, with a note.
    """
    baseline: dict[str, int] = {}
    streak: dict[str, tuple[int, int]] = {}  # key -> (lower total, listings in a row at it)
    alerts: list[str] = []
    notes: list[str] = []
    for totals in history:
        alerts, notes = [], []
        for key, total in totals.items():
            base = baseline.get(key)
            if base is None or total >= base * (1 - DROP_SHARE):
                baseline[key] = total
                streak.pop(key, None)
                continue
            lower, count = streak.get(key, (None, 0))
            count = count + 1 if lower == total else 1
            if count >= ACCEPT_AFTER:
                baseline[key] = total
                streak.pop(key, None)
                notes.append(f"{label(key)}: total {total} accepted as the new baseline after {ACCEPT_AFTER} "
                             f"runs in a row at it (was {base})")
            else:
                streak[key] = (total, count)
                alerts.append(f"ALERT: {label(key)} total dropped from {base} to {total} ({(total - base) / base:.0%}, "
                              f"more than {DROP_SHARE:.0%}; run {count} of {ACCEPT_AFTER} at this total): "
                              f"nothing deactivated")
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
                   scraped_at: datetime) -> tuple[list[str], list[str]]:
    """(alerts, notes) of a Preunic scrape file being loaded (before its listings are written)."""
    known_in_store = cursor.execute("SELECT count(*) FROM raw_listings WHERE store_id = %s",
                                    (store_id,)).fetchone()[0]
    known_read = cursor.execute("SELECT count(*) FROM raw_listings WHERE store_id = %s AND listing_url = ANY(%s)",
                                (store_id, urls)).fetchone()[0]
    alerts = new_listing_alert(known_in_store, known_read, len(urls))
    notes: list[str] = []
    totals = listing_totals(data)
    if totals:  # a listing that is not whole is already partial
        drops, notes = drop_alerts(earlier_totals(path.parent, data["store"], scraped_at) + [totals])
        alerts += drops
    return alerts, notes
