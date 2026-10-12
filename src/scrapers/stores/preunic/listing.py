"""Preunic's category order has ties: which listing comes first can change between requests.

"Load more" adds 24 cards at a time, each batch asked for separately. When two
tied listings swap places between two batch requests, the swap straddles the
boundary: one of them shows up in both batches and the other in neither. On
2026-10-08 one listing was repeated and one missing (cut 47|48); on 2026-10-12
four of each (cuts 311|312, 407|408, 455|456), all sets/estuches.

The scraper reads the listing once. If its distinct URLs match the page's total
it is used as it is. Otherwise it reads the listing a second time (the same
page load and clicks, nothing more) and choose_listing() decides:

1. the second pass alone matches its total: use it alone (one moment of the
   catalog, nothing mixed);
2. else the union of both passes, which is complete only if (i) both passes
   saw the same page total, (ii) the union's distinct URLs equal it, and (iii)
   every URL seen in only one pass sits, in that pass, within TOLERANCE
   positions of a batch boundary: where the ties swap. A listing that left or
   entered the catalog between the passes can sit anywhere.
3. A rejected union keeps its prices, but listing_complete is False: the loader
   then deactivates nothing, whatever the counts say.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any

# How far from a batch boundary (between cards end-1 and end) a URL seen in only
# one pass may sit. The four ties of 2026-10-12 were at most one card away.
TOLERANCE = 1

FIRST_PASS, SECOND_PASS, UNION = "first_pass", "second_pass", "union"


@dataclass
class ListingPass:
    urls: list[str]           # card URLs in page order, repeats included
    site_total: int | None    # the page's "N productos"
    batch_ends: list[int]     # cards shown after the first load and after each "load more" click

    def distinct(self) -> list[str]:
        return list(dict.fromkeys(self.urls))

    def positions(self) -> dict[str, list[int]]:
        found: dict[str, list[int]] = defaultdict(list)
        for position, url in enumerate(self.urls):
            found[url].append(position)
        return found

    def repeated(self) -> list[dict[str, Any]]:
        return [{"url": url, "positions": positions}
                for url, positions in self.positions().items() if len(positions) > 1]

    def complete(self) -> bool:
        return self.site_total is not None and len(set(self.urls)) == self.site_total

    def summary(self) -> dict[str, Any]:
        return {"site_total": self.site_total, "cards": len(self.urls), "distinct": len(set(self.urls)),
                "repeated": self.repeated(), "batch_ends": self.batch_ends}


def near_a_batch_boundary(position: int, batch_ends: list[int], tolerance: int = TOLERANCE) -> bool:
    """Is the card at this position within `tolerance` cards of a boundary between two batches?"""
    return any(end - 1 - tolerance <= position <= end + tolerance for end in batch_ends[:-1])


def choose_listing(first: ListingPass, second: ListingPass | None) -> dict[str, Any]:
    """Which URLs make the listing, where they come from, and whether it is the whole catalog."""
    if first.complete() or second is None:
        return {"listing_source": FIRST_PASS, "urls": first.distinct(), "listing_complete": first.complete(),
                "recovered": [], "union_rejected": None}
    if second.complete():
        return {"listing_source": SECOND_PASS, "urls": second.distinct(), "listing_complete": True,
                "recovered": [], "union_rejected": None}

    urls = list(dict.fromkeys(first.urls + second.urls))
    recovered = [url for url in second.distinct() if url not in set(first.urls)]
    rejected = None
    if first.site_total is None or first.site_total != second.site_total:
        rejected = {"condition": "same_page_total",
                    "detail": f"the page reported {first.site_total} then {second.site_total} products"}
    elif len(urls) != first.site_total:
        rejected = {"condition": "union_matches_total",
                    "detail": f"the union has {len(urls)} distinct listings, the page reports {first.site_total}"}
    else:
        away = []
        for one, other in ((first, second), (second, first)):
            positions, others = one.positions(), set(other.urls)
            away += [{"url": url, "positions": spots} for url, spots in positions.items()
                     if url not in others and not all(near_a_batch_boundary(p, one.batch_ends) for p in spots)]
        if away:
            rejected = {"condition": "differences_at_batch_boundaries",
                        "detail": f"{len(away)} listings seen in only one pass are not next to a batch boundary "
                                  f"(a catalog change, not a tie)", "listings": away}
    return {"listing_source": UNION, "urls": urls, "listing_complete": rejected is None,
            "recovered": recovered, "union_rejected": rejected}
