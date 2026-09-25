"""Evaluate the matching rules against every human-labeled pair.

Usage:
    python -m src.matching.evaluate

Runs the pipeline decisions WITHOUT human overrides (otherwise the labels
would be graded against themselves) and compares them with
data/labeled/*.csv. A pair is "correct" if it is labeled "same", or
"same_fragrance_unknown_size" and both volumes are now known and equal.
"""

from __future__ import annotations

import csv
import os
from collections import Counter
from pathlib import Path

import psycopg

from src.loader.raw_listings import DEFAULT_DATABASE_URL
from src.matching.pipeline import LABELED_DIRECTORY, Listing, decide, load_listings, one_to_one


def load_labels(directory: Path = LABELED_DIRECTORY) -> dict[frozenset[str], tuple[str, str]]:
    """{url pair: (label, file name)}; later files do not override earlier conflicting labels."""
    labels: dict[frozenset[str], tuple[str, str]] = {}
    conflicts = []
    for path in sorted(directory.glob("*.csv")):
        for row in csv.DictReader(path.open(encoding="utf-8")):
            label = (row.get("label") or "").strip()
            if not label:
                continue
            pair = frozenset((row["preunic_url"], row["maicao_url"]))
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


def evaluate(listings: list[Listing], labels: dict[frozenset[str], tuple[str, str]]) -> dict:
    decisions = decide(listings, overrides=None)
    accepted = {frozenset((listings[d.a].url, listings[d.b].url)): d for d in one_to_one(listings, decisions)}
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
    return {
        "listings": len(listings),
        "auto_accepted": len(accepted),
        "auto_accepted_labeled": len(labeled_accepted),
        "auto_accepted_correct": len(correct_accepted),
        "outcome_by_label": outcome_by_label,
        "wrong_merges": wrong_merges,
        "missed_by_veto": missed,
        "decisions": Counter(d.kind for d in decisions),
    }


def main() -> None:
    with psycopg.connect(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)) as connection:
        listings = load_listings(connection)
    labels = load_labels()
    report = evaluate(listings, labels)

    n, k, total = report["auto_accepted_labeled"], report["auto_accepted_correct"], report["auto_accepted"]
    print(f"{report['listings']} listings | {len(labels)} labeled pairs | candidate decisions {dict(report['decisions'])}")
    print(f"\nAUTO-MATCH PRECISION: {k}/{n} labeled accepted pairs correct"
          + (f" = {k / n:.1%}" if n else "")
          + f"   (coverage: {n}/{total} accepted pairs labeled"
          + (" -> exact" if n == total else " -> estimate") + ")")
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
