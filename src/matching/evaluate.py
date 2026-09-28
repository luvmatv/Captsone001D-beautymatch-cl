"""Evaluate the matching rules against every human-labeled pair.

Usage:
    python -m src.matching.evaluate

Runs the pipeline decisions WITHOUT human overrides (otherwise the labels
would be graded against themselves) and compares them with
data/labeled/*.csv. A pair is "correct" if it is labeled "same", or
"same_fragrance_unknown_size" and both volumes are now known and equal.
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from itertools import combinations
from pathlib import Path

import psycopg

from src.loader.raw_listings import DEFAULT_DATABASE_URL
from src.matching.pipeline import (
    LABELED_DIRECTORY,
    MATCHING_STORES,
    Listing,
    _same_store_listings_agree,
    decide,
    labeled_pair,
    load_listings,
    match_groups,
    one_to_one,
    ordered_pair,
)


def load_labels(directory: Path = LABELED_DIRECTORY) -> dict[frozenset[str], tuple[str, str]]:
    """{url pair: (label, file name)}; later files do not override earlier conflicting labels."""
    labels: dict[frozenset[str], tuple[str, str]] = {}
    conflicts = []
    for path in sorted(directory.glob("*.csv")):
        for row in csv.DictReader(path.open(encoding="utf-8")):
            label = (row.get("label") or "").strip()
            pair = labeled_pair(row)
            if not label or not pair:
                continue
            if pair in labels and labels[pair][0] != label:
                conflicts.append((path.name, labels[pair], label))
            labels.setdefault(pair, (label, path.name))
    if conflicts:
        print("WARNING conflicting labels:", conflicts)
    return labels


def is_correct(label: str, a: Listing, b: Listing) -> bool:
    if label == "same":
        return True
    return label == "same_fragrance_unknown_size" and bool(a.volume_ml) and a.volume_ml == b.volume_ml


def store_pair(a: Listing, b: Listing) -> str:
    first, second = ordered_pair(a, b)
    return f"{first.store}-{second.store}"


def evaluate(listings: list[Listing], labels: dict[frozenset[str], tuple[str, str]]) -> dict:
    decisions = decide(listings, overrides=None)
    accepted_decisions = one_to_one(listings, decisions)
    groups = match_groups(listings, accepted_decisions)
    # Every pair of listings that ends up in one product: the accepted pairs and,
    # with three or more stores, the pairs joined through a chain (P-M + M-S => P-S).
    # A store's own duplicates in a group (same listing_key) are not cross-store matches.
    accepted = {frozenset((listings[a].url, listings[b].url)): (a, b)
                for group in groups for a, b in combinations(group, 2) if listings[a].store != listings[b].store}
    direct = {frozenset((listings[d.a].url, listings[d.b].url)) for d in accepted_decisions}
    by_pair = {frozenset((listings[d.a].url, listings[d.b].url)): d for d in decisions}
    index_by_url = {listing.url: i for i, listing in enumerate(listings)}

    outcome_by_label: Counter = Counter()
    wrong_merges, missed = [], []
    for pair, (label, source) in labels.items():
        urls = sorted(pair)
        if any(url not in index_by_url for url in urls):
            outcome_by_label[(label, "listing_missing")] += 1
            continue
        a, b = (listings[index_by_url[url]] for url in urls)
        decision = by_pair.get(pair)
        if pair in accepted:
            outcome = "matched"
        elif decision is None:
            outcome = "not_a_candidate"
        elif decision.kind == "auto":
            outcome = "auto_but_lost_one_to_one"
        else:
            outcome = f"{decision.kind}:{decision.reason}"
        outcome_by_label[(label, outcome.split(":")[0] if outcome.startswith("review") else outcome)] += 1
        correct = is_correct(label, a, b)
        if outcome == "matched" and not correct:
            wrong_merges.append((source, label, a.name, b.name))
        if correct and outcome.startswith("veto"):
            missed.append((source, outcome, a.name, b.name))

    labeled_accepted = [pair for pair in accepted if pair in labels]
    correct_accepted = [
        pair for pair in labeled_accepted
        if is_correct(labels[pair][0], *(listings[index_by_url[url]] for url in sorted(pair)))
    ]
    by_stores: dict[str, Counter] = {}
    for pair, (a, b) in accepted.items():
        counts = by_stores.setdefault(store_pair(listings[a], listings[b]), Counter())
        counts["accepted"] += 1
        counts["through_a_chain"] += pair not in direct
        counts["labeled"] += pair in labels
        counts["correct"] += pair in correct_accepted
    for decision in decisions:
        counts = by_stores.setdefault(store_pair(listings[decision.a], listings[decision.b]), Counter())
        counts["candidates"] += 1
        counts[decision.kind] += 1
    return {
        "listings": len(listings),
        "auto_accepted": len(accepted),
        "auto_accepted_labeled": len(labeled_accepted),
        "auto_accepted_correct": len(correct_accepted),
        "by_stores": by_stores,
        # Two listings of one store in a group are allowed only as the same product
        # listed twice (identical listing_key); anything else is a merge within a store.
        "groups_with_store_duplicates": sum(
            len(group) != len({listings[i].store for i in group}) for group in groups),
        "inconsistent_groups": sum(
            not _same_store_listings_agree(listings, group, frozenset(
                store for store, n in Counter(listings[i].store for i in group).items() if n > 1))
            for group in groups),
        "outcome_by_label": outcome_by_label,
        "wrong_merges": wrong_merges,
        "missed_by_veto": missed,
        "decisions": Counter(d.kind for d in decisions),
    }


def precision_line(k: int, n: int, total: int) -> str:
    return (f"{k}/{n} labeled accepted pairs correct" + (f" = {k / n:.1%}" if n else "")
            + f"   (coverage: {n}/{total} accepted pairs labeled" + (" -> exact" if n == total else " -> estimate") + ")")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the matching rules against the labeled pairs")
    parser.add_argument("--stores", default=",".join(MATCHING_STORES),
                        help=f"comma-separated stores (default: {','.join(MATCHING_STORES)})")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()
    stores = tuple(store.strip() for store in args.stores.split(",") if store.strip())
    with psycopg.connect(args.database_url) as connection:
        listings = load_listings(connection, stores)
    labels = load_labels()
    report = evaluate(listings, labels)

    n, k, total = report["auto_accepted_labeled"], report["auto_accepted_correct"], report["auto_accepted"]
    print(f"{report['listings']} listings | {len(labels)} labeled pairs | candidate decisions {dict(report['decisions'])}")
    print(f"\nAUTO-MATCH PRECISION: {precision_line(k, n, total)}")
    print("\nBY STORE PAIR:")
    for stores_key, counts in sorted(report["by_stores"].items()):
        print(f"    {stores_key:22} candidates {counts['candidates']:4} (auto {counts['auto']}, review {counts['review']}, "
              f"veto {counts['veto']}) | accepted {counts['accepted']} ({counts['through_a_chain']} through a chain) | "
              + precision_line(counts["correct"], counts["labeled"], counts["accepted"]))
    print(f"\nGROUPS WITH A STORE DUPLICATE (same product listed twice): {report['groups_with_store_duplicates']}")
    print(f"INCONSISTENT GROUPS (a store repeated with different products): {report['inconsistent_groups']}")
    print(f"\nWRONG MERGES ({len(report['wrong_merges'])}):")
    for row in report["wrong_merges"]:
        print("   ", row)
    print(f"\nCORRECT PAIRS VETOED ({len(report['missed_by_veto'])}):")
    for row in report["missed_by_veto"]:
        print("   ", row)
    print("\nOUTCOME BY LABEL:")
    for (label, outcome), count in sorted(report["outcome_by_label"].items()):
        print(f"    {label:28} {outcome:28} {count}")


if __name__ == "__main__":
    main()
