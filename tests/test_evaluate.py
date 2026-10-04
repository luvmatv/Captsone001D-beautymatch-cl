"""Evaluation by store pair, including pairs joined through a chain of matches."""

import numpy as np

from src.matching import evaluate as evaluation
from src.matching.pipeline import Decision, Listing


def listing(n, store, name="Shakira Fucsia Elixir EDP 50 ml"):
    return Listing(f"id{n}", store, "Shakira", name, 50, "edp", f"https://{store}/{n}", np.array([1.0, 0.0]))


ITEMS = [listing(0, "preunic"), listing(1, "maicao"), listing(2, "salcobrand")]
# P-M and M-S accepted; P-S was never compared (not among each other's top
# candidates, like "Mediterraneo"), but the chain puts it in the same product.
DECISIONS = [Decision(0, 1, 0.99, "auto", "same_name"), Decision(1, 2, 0.98, "auto", "same_name")]


def run(monkeypatch, labels, decisions=DECISIONS):
    monkeypatch.setattr(evaluation, "decide", lambda listings, overrides=None: decisions)
    return evaluation.evaluate(ITEMS, labels)


def pair(a, b):
    return frozenset((ITEMS[a].url, ITEMS[b].url))


def test_pairs_joined_through_a_chain_are_evaluated(monkeypatch) -> None:
    report = run(monkeypatch, {pair(0, 1): ("same", "f.csv"), pair(0, 2): ("different", "f.csv")})
    assert report["auto_accepted"] == 3                          # P-M, M-S and the implied P-S
    assert report["by_stores"]["preunic-salcobrand"]["through_a_chain"] == 1
    assert report["wrong_merges"] == [("f.csv", "different", ITEMS[0].name, ITEMS[2].name)]
    assert (report["auto_accepted_labeled"], report["auto_accepted_correct"]) == (2, 1)


def test_a_vetoed_pair_is_not_joined_through_a_chain(monkeypatch) -> None:
    report = run(monkeypatch, {}, DECISIONS + [Decision(0, 2, 0.90, "veto", "concentration")])
    assert report["auto_accepted"] == 1                          # P-M only: M-S would join the vetoed P-S
    assert "preunic-salcobrand" not in {k for k, v in report["by_stores"].items() if v["accepted"]}


def test_counts_by_store_pair_use_a_fixed_store_order(monkeypatch) -> None:
    report = run(monkeypatch, {}, DECISIONS + [Decision(0, 2, 0.90, "veto", "concentration")])
    assert set(report["by_stores"]) == {"preunic-maicao", "maicao-salcobrand", "preunic-salcobrand"}
    assert report["by_stores"]["preunic-maicao"]["accepted"] == 1
    assert report["by_stores"]["preunic-salcobrand"]["veto"] == 1
    assert (report["groups_with_store_duplicates"], report["inconsistent_groups"]) == (0, 0)


def test_products_with_two_listings_of_one_store_are_listed(monkeypatch) -> None:
    # a store listing the same product twice (identical key) is one product with both listings
    items = ITEMS + [listing(3, "preunic", "EDP Shakira Fucsia Elixir 50 ml"), listing(4, "maicao", "Shakira Dance 50 ml")]
    monkeypatch.setattr(evaluation, "decide", lambda listings, overrides=None: DECISIONS)
    report = evaluation.evaluate(items, {})
    assert report["same_store_products"] == [
        ("preunic", sorted([ITEMS[0].name, "EDP Shakira Fucsia Elixir 50 ml"])),
    ]
