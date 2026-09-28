"""Evaluation by store pair, including pairs joined through a chain of matches."""

import numpy as np

from src.matching import evaluate as evaluation
from src.matching.pipeline import Decision, Listing


def listing(n, store, name="Shakira Fucsia Elixir EDP 50 ml"):
    return Listing(f"id{n}", store, "Shakira", name, 50, "edp", f"https://{store}/{n}", np.array([1.0, 0.0]))


ITEMS = [listing(0, "preunic"), listing(1, "maicao"), listing(2, "salcobrand")]
# P-M and M-S accepted; P-S itself vetoed, but the chain puts it in the same product
DECISIONS = [Decision(0, 1, 0.99, "auto", "same_name"), Decision(1, 2, 0.98, "auto", "same_name"),
             Decision(0, 2, 0.90, "veto", "name")]


def run(monkeypatch, labels):
    monkeypatch.setattr(evaluation, "decide", lambda listings, overrides=None: DECISIONS)
    return evaluation.evaluate(ITEMS, labels)


def pair(a, b):
    return frozenset((ITEMS[a].url, ITEMS[b].url))


def test_pairs_joined_through_a_chain_are_evaluated(monkeypatch) -> None:
    report = run(monkeypatch, {pair(0, 1): ("same", "f.csv"), pair(0, 2): ("different", "f.csv")})
    assert report["auto_accepted"] == 3                          # P-M, M-S and the implied P-S
    assert report["by_stores"]["preunic-salcobrand"]["through_a_chain"] == 1
    assert report["wrong_merges"] == [("f.csv", "different", ITEMS[0].name, ITEMS[2].name)]
    assert (report["auto_accepted_labeled"], report["auto_accepted_correct"]) == (2, 1)


def test_counts_by_store_pair_use_a_fixed_store_order(monkeypatch) -> None:
    report = run(monkeypatch, {})
    assert set(report["by_stores"]) == {"preunic-maicao", "maicao-salcobrand", "preunic-salcobrand"}
    assert report["by_stores"]["preunic-maicao"]["accepted"] == 1
    assert report["by_stores"]["preunic-salcobrand"]["veto"] == 1
    assert report["groups_with_a_repeated_store"] == 0
