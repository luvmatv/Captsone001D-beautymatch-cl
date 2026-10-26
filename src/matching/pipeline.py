"""Cross-store matching: candidates -> vetoes -> decision -> one-to-one -> canonical rows.

Usage:
    python -m src.matching.pipeline              # upsert fragrances/products, export review queue
    python -m src.matching.pipeline --dry-run    # print the plan, write nothing
    python -m src.matching.pipeline --no-overrides
    python -m src.matching.pipeline --dry-run --stores preunic,maicao,salcobrand

Only MATCHING_STORES are matched by default; listings of other stores are
not loaded here and write_plan never touches them (they stay pending).

Stages:
1. Candidates: for every listing, the TOP_K most similar same-brand listings of
   each other store (embeddings are normalized, so cosine = dot product). Both
   directions are unioned. Similarity only ranks; it never decides.
2. Vetoes: brand, volume and concentration when known on both sides, then the
   rules in src/matching/rules.py (gender, presentation, generic name, variant,
   distinct name).
3. Decision: "auto" when the names match (identical core or typo-only) and the
   volume is known and equal on both sides; anything else that survived the
   vetoes goes to the review queue.
4. Grouping: auto pairs are accepted by descending similarity into groups with
   at most one listing per store (except a store's exact duplicates) and no
   pair the rules vetoed.
5. Canonical rows: matched groups and unmatched listings with a known volume
   become products; products that share brand, name core, gender and edition
   number share a fragrance. A listing with an open review pair is a product
   of its own meanwhile (visible); only listings without a volume stay pending.

Human labels in data/labeled/*.csv override the rules for the pairs they
cover ("same" -> match, "different" -> veto, other labels -> review).
"""

from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import logging
import os
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg

from src.db_config import load_env_file
from src.loader.raw_listings import DEFAULT_DATABASE_URL
from src.matching.normalization import repair_mojibake
from src.matching.rules import (
    DESCRIPTIVE_GENDER_WORDS,
    GENDER_WORDS,
    NEUTRAL_WORDS,
    SAME_WORD_MAX_DISTANCE,
    GenderIndex,
    gender,
    identity_key,
    is_generic,
    is_set,
    marker_gender_conflict,
    name_with_gender_markers,
    same_brand,
    same_name,
    store_listing_words,
    veto,
    with_declared_gender,
    word_distance,
)
from src.db_lock import DatabaseBusy, LockLost, acquire_writer_lock, writer_connection
from src.schema_check import SchemaNotUpToDate, require_current_schema
from src.scrapers.volume import VOLUME_PATTERN

logger = logging.getLogger(__name__)

TOP_K = 5
# Stores the matching runs on. Other stores can be scraped and loaded (their
# price history accumulates) but their listings stay pending, with no
# product, until the rules are calibrated for them. Salcobrand joined after a
# labeled random sample: 30/30 correct with Preunic, 30/30 with Maicao.
# dperfumes joined on 2026-10-21 with its declared gender read like a store
# code (docs/known_data_issues.md); precision sample in
# data/labeled/dperfumes_precision_v1.csv. Dreams Parfums: precision sample in
# data/labeled/dreamsparfums_precision_v1.csv.
MATCHING_STORES = ("preunic", "maicao", "salcobrand", "beautyperfumes", "dperfumes", "dreamsparfums")
LABELED_DIRECTORY = Path("data/labeled")
REVIEW_DIRECTORY = Path("artifacts/review")
ABBREVIATED = re.compile(r"[A-Za-z]\.[A-Za-z]|[A-Za-z]{2}\d{2,}", re.IGNORECASE)  # "GR.MOD", "SP236ML"
CONCENTRATION_LABELS = {"edp": "EDP", "edt": "EDT", "cologne": "EDC", "parfum": "Parfum",
                        "eau_fraiche": "Eau Fraîche", "other": ""}


@dataclass(frozen=True)
class Listing:
    id: str
    store: str
    brand: str | None
    name: str
    volume_ml: int | None
    concentration: str | None
    url: str
    embedding: np.ndarray = field(repr=False, compare=False)

    @property
    def key(self) -> tuple[str | None, str]:
        return (self.brand, self.name)


@dataclass(frozen=True)
class Decision:
    a: int  # index into the listings list
    b: int
    similarity: float
    kind: str  # "auto" | "review" | "veto"
    reason: str


# ---------------------------------------------------------------- stages 1-3


def candidates(listings: list[Listing], top_k: int = TOP_K) -> list[tuple[int, int, float]]:
    """(a, b, similarity) with a < b, from top-k same-brand neighbours in both directions."""
    by_store: dict[str, list[int]] = defaultdict(list)
    for index, listing in enumerate(listings):
        by_store[listing.store].append(index)
    vectors = np.stack([listing.embedding for listing in listings])
    # Millions of listing pairs but only tens of thousands of brand pairs: compute each once.
    brand_match = functools.cache(same_brand)
    pairs: dict[tuple[int, int], float] = {}
    for store, members in by_store.items():
        for other_store, others in by_store.items():
            if other_store == store:
                continue
            similarity = vectors[members] @ vectors[others].T
            for row, a in enumerate(members):
                # stable: neighbours of equal similarity rank by listing order, not by np.argsort's whim
                ranked = [others[col] for col in np.argsort(-similarity[row], kind="stable")
                          if brand_match(listings[a].brand, listings[others[col]].brand)][:top_k]
                for b in ranked:
                    pairs[(min(a, b), max(a, b))] = float(vectors[a] @ vectors[b])
    return [(a, b, s) for (a, b), s in pairs.items()]


def classify(a: Listing, b: Listing, genders: GenderIndex,
             marked_genders: GenderIndex | None = None) -> tuple[str, str]:
    """Stage 2 and 3 for one pair: ("veto"|"auto"|"review", reason).

    With marked_genders (the catalog with the stores' gender codes read), a pair
    the name rules do not veto goes to review when its gender rests only on a
    store code (marker_gender_conflict).

    Two generic names ("Perfume Shakira 50 ml", Maicao's "Eau De Cologne 200
    mL") are never accepted by the rules alone: such a pair goes to review and
    needs a human label (human labels are applied before this, in decide). On
    2026-10-05 every generic pair in a product was labeled; two were not and
    the rules would have accepted them (a generic EDT with an Agua Brava).
    """
    kind, reason = _classify_names(a, b, genders)
    if kind != "veto" and marked_genders is not None and marker_gender_conflict(
            (a.store, a.brand, a.name), (b.store, b.brand, b.name), marked_genders):
        return "review", "gender_marker"
    if kind == "auto" and is_generic(a.brand, a.name) and is_generic(b.brand, b.name):
        return "review", "generic_pair"
    return kind, reason


def _classify_names(a: Listing, b: Listing, genders: GenderIndex) -> tuple[str, str]:
    if not same_brand(a.brand, b.brand):
        return "veto", "brand"
    if a.volume_ml and b.volume_ml and a.volume_ml != b.volume_ml:
        return "veto", "volume"
    if a.concentration and b.concentration and a.concentration != b.concentration:
        return "veto", "concentration"
    reason = veto(a.key, b.key, genders)
    if reason:
        return "veto", reason
    if not same_name(a.key, b.key):
        return "review", "extra_words"
    if not (a.volume_ml and b.volume_ml):
        return "review", "unknown_volume"
    return "auto", "same_name"


# Labeled CSVs name the two listings of a pair with store-neutral columns
# (store_a, url_a, store_b, url_b, ...). The first files, from when there were
# two stores, use preunic_url / maicao_url; both are read. The pair is keyed by
# its URLs regardless of order.
PAIR_URL_COLUMNS = (("url_a", "url_b"), ("preunic_url", "maicao_url"))


def labeled_pair(row: dict[str, str]) -> frozenset[str] | None:
    for column_a, column_b in PAIR_URL_COLUMNS:
        if row.get(column_a) and row.get(column_b):
            return frozenset((row[column_a].strip(), row[column_b].strip()))
    return None


def load_overrides(directory: Path = LABELED_DIRECTORY) -> dict[frozenset[str], str]:
    """Human labels keyed by the pair of listing URLs."""
    overrides: dict[frozenset[str], str] = {}
    for path in sorted(directory.glob("*.csv")):
        for row in csv.DictReader(path.open(encoding="utf-8")):
            label = (row.get("label") or "").strip()
            pair = labeled_pair(row)
            if label and pair:
                overrides[pair] = label
    return overrides


def decide(
    listings: list[Listing],
    overrides: dict[frozenset[str], str] | None = None,
    top_k: int = TOP_K,
) -> list[Decision]:
    genders = GenderIndex(
        (listing.store, listing.brand, listing.name, listing.volume_ml, listing.concentration)
        for listing in listings
    )
    marked_genders = GenderIndex(
        (listing.store, listing.brand, name_with_gender_markers(listing.store, listing.name),
         listing.volume_ml, listing.concentration)
        for listing in listings
    )
    overrides = overrides or {}
    pairs = {(a, b): s for a, b, s in candidates(listings, top_k)}
    # A labeled pair is always considered, even if it is not among the top-k neighbours.
    index_by_url = {listing.url: i for i, listing in enumerate(listings)}
    for urls in overrides:
        indexes = sorted(index_by_url[url] for url in urls if url in index_by_url)
        if len(indexes) == 2 and tuple(indexes) not in pairs:
            a, b = indexes
            pairs[(a, b)] = float(listings[a].embedding @ listings[b].embedding)
    # Decisions in (a, b) order. Listings come ordered by store and raw_listing_id,
    # so pairs of equal similarity keep one order whatever else the catalog holds:
    # one_to_one takes ties in this order. Before, the order followed when a pair
    # was first found, which shifted with the catalog, and Halloween Man / Man X
    # (an exact tie) swapped partners between runs 56, 57 and 58.
    decisions = []
    for (a, b), similarity in sorted(pairs.items()):
        human = overrides.get(frozenset((listings[a].url, listings[b].url)))
        if human == "same":
            kind, reason = "auto", "human_same"
        elif human == "different":
            kind, reason = "veto", "human_different"
        elif human:
            kind, reason = "review", f"human_{human}"
        else:
            kind, reason = classify(listings[a], listings[b], genders, marked_genders)
        decisions.append(Decision(a, b, similarity, kind, reason))
    return decisions


# ------------------------------------------------------------------ stage 4


class _Groups:
    """Union-find over listing indexes that remembers the stores in each group."""

    def __init__(self, listings: list[Listing]) -> None:
        self.parent: dict[int, int] = {}
        self.stores: dict[int, frozenset[str]] = {}
        self.members: dict[int, list[int]] = {}
        self.listings = listings

    def find(self, i: int) -> int:
        self.parent.setdefault(i, i)
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def stores_of(self, root: int) -> frozenset[str]:
        return self.stores.get(root, frozenset({self.listings[root].store}))

    def members_of(self, root: int) -> list[int]:
        return self.members.get(root, [root])

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.stores[root_a] = self.stores_of(root_a) | self.stores_of(root_b)
            self.members[root_a] = self.members_of(root_a) + self.members_of(root_b)
            self.parent[root_b] = root_a


def listing_key(listing: Listing) -> tuple | None:
    """The product a listing is, from the listing alone: fragrance identity,
    concentration, volume and presentation. None without a volume."""
    if not listing.volume_ml:
        return None
    presentation = "travel_set" if is_set(listing.name) else "full_bottle"
    return (identity_key(listing.brand, listing.name, listing.store), listing.concentration, listing.volume_ml,
            presentation)


def _store_words(listing: Listing) -> tuple[str, ...]:
    return store_listing_words(listing.brand, listing.name, listing.volume_ml)


def _same_store_listings_agree(listings: list[Listing], members: list[int], stores: frozenset[str]) -> bool:
    """Listings of one store may share a group only if they are the same product
    (a store publishing it twice): exactly the same listing_key, nothing looser,
    and the same name but for what a store writes differently (store_listing_words)."""
    for store in stores:
        own = [listings[i] for i in members if listings[i].store == store]
        keys = {listing_key(listing) for listing in own}
        if len(keys) != 1 or None in keys or len({_store_words(listing) for listing in own}) != 1:
            return False
    return True


def _compatible(listings: list[Listing], one: list[int], other: list[int],
                apart: frozenset[frozenset[int]] = frozenset()) -> bool:
    """Two groups with one product key can be one product: their listings of a common store
    agree, and no pair across them is labeled "different" by a human (apart)."""
    if any(frozenset((a, b)) in apart for a in one for b in other):
        return False
    words: dict[str, set] = defaultdict(set)
    for i in one + other:
        words[listings[i].store].add(_store_words(listings[i]))
    return all(len(found) == 1 for found in words.values())


def _split_by_store_words(listings: list[Listing], groups: list[list[int]], identity: tuple,
                          apart: frozenset[frozenset[int]] = frozenset()) -> list[tuple[tuple, list[list[int]]]]:
    """(identity, groups) of the products that groups sharing one product key become.

    Groups whose listings of a common store agree are one product (a store
    listing it twice). Groups that do not are kept apart: the one with the
    fewest words of its own keeps the key (and so the name); each other one
    adds to its identity the words that tell it apart. The product ID is not
    decided here: assign_product_ids gives it to the part with more price history.
    A human "different" label (apart) also keeps two groups apart: an identical key
    never overrides it (Animale for Men, labeled sample 2026-10-21).
    """
    clusters: list[list[list[int]]] = []  # each: the groups that are one product
    for group in groups:
        home = next((cluster for cluster in clusters
                     if _compatible(listings, [i for g in cluster for i in g], group, apart)), None)
        if home is None:
            clusters.append([group])
        else:
            home.append(group)
    if len(clusters) == 1:
        return [(identity, clusters[0])]
    members = [[i for g in cluster for i in g] for cluster in clusters]
    store_count = Counter(store for part in members for store in {listings[i].store for i in part})
    shared = {store for store, n in store_count.items() if n > 1}
    words = [Counter(w for i in part if listings[i].store in shared for w in _store_words(listings[i]))
             for part in members]
    base = min(range(len(clusters)), key=lambda n: (sum(words[n].values()), sorted(words[n].elements())))
    # Parts kept apart only by a human label may share no store: then their own words tell them apart.
    own = [Counter(w for i in part for w in _store_words(listings[i])) for part in members]
    brand_key, core, gender_, editions = identity
    result, taken = [], {core}
    for n, cluster in enumerate(clusters):
        if n == base:
            result.append((identity, cluster))
            continue
        extra = (list((words[n] - words[base]).elements()) or list(words[n].elements())
                 or list((own[n] - own[base]).elements()) or list(own[n].elements()))
        part_core = tuple(sorted(core + tuple(extra)))
        while part_core in taken:  # never two parts with one key: the key is what makes them one product
            part_core = tuple(sorted(part_core + ("apart",)))
        taken.add(part_core)
        result.append(((brand_key, part_core, gender_, editions), cluster))
    return result


def one_to_one(listings: list[Listing], decisions: list[Decision]) -> list[Decision]:
    """Accept auto pairs by descending similarity while every group of matched
    listings stays consistent.

    With two stores that is one partner per listing. With more, the pairs of
    one perfume chain into a group (P-M, M-S, P-S). A pair is not accepted if
    its group would get
    - two listings of the same store (P1-M1, M1-S1, then S1-P2), unless they
      are the same product listed twice by that store (identical listing_key:
      Salcobrand lists "Body Splash Itzy Fantasy 250 ml" and "Body Splash
      Fantasy 250ml"), or
    - two listings the rules vetoed as a pair: a Salcobrand name without
      concentration matches both a Preunic "Colonia" and a Maicao "EDT", but
      that Preunic-Maicao pair was vetoed, so the chain must not join them.
    """
    vetoed = {frozenset((d.a, d.b)) for d in decisions if d.kind == "veto"}
    groups = _Groups(listings)
    accepted = []
    for decision in sorted((d for d in decisions if d.kind == "auto"), key=lambda d: -d.similarity):
        root_a, root_b = groups.find(decision.a), groups.find(decision.b)
        if root_a != root_b:
            repeated = groups.stores_of(root_a) & groups.stores_of(root_b)
            members = groups.members_of(root_a) + groups.members_of(root_b)
            if repeated and not _same_store_listings_agree(listings, members, repeated):
                continue
            if any(frozenset((x, y)) in vetoed for x in groups.members_of(root_a) for y in groups.members_of(root_b)):
                continue
        groups.union(decision.a, decision.b)
        accepted.append(decision)
    return accepted


def match_groups(listings: list[Listing], accepted: list[Decision]) -> list[list[int]]:
    """The groups (connected components) formed by the accepted pairs.

    Groups come in the order of their most similar pair, as the pairs did
    before groups existed: fragrance name disambiguation depends on it.
    """
    groups = _Groups(listings)
    for decision in accepted:
        groups.union(decision.a, decision.b)
    members: dict[int, list[int]] = defaultdict(list)
    for index in sorted(groups.parent):
        members[groups.find(index)].append(index)
    order: dict[int, int] = {}
    for rank, decision in enumerate(accepted):
        order.setdefault(groups.find(decision.a), rank)
    return [members[root] for root in sorted(members, key=order.__getitem__)]


# ------------------------------------------------------------------ stage 5


def display_brand(brands: list[str | None]) -> str:
    written = [b.strip() for b in brands if b and b.strip()]
    mixed = [b for b in written if not b.isupper()]
    return (Counter(mixed).most_common(1)[0][0] if mixed else written[0].title()) if written else ""


def display_name(brand: str | None, name: str, *brands: str | None) -> str:
    """Listing name without brand, size, format and audience words, in original order.

    Returns "" when nothing identifying is left ("Eau De Toilette con Vaporizador").
    Brand words are removed with typo tolerance ("Lattafa" when the store says "Lataffa").
    """
    brand_words = {w for b in (brand, *brands) for w in (b or "").lower().split()}
    kept = []
    name = re.sub(r"\(\w\)", " ", name)  # Maicao's "(M)" / "(F)" audience tags
    # dashes between words: "Fucsia - Edp", and dperfumes' "Cool Water EDT 100 ml – Davidoff"
    name = re.sub(r"\s[-–—]\s|\s[-–—]$", " ", name)
    for token in VOLUME_PATTERN.sub(" ", name).replace("+", " ").split():
        word = token.strip(".,()").lower()
        if not word or word in DESCRIPTIVE_GENDER_WORDS or word == "para":
            continue
        if any(word == b or (len(word) > 3 and word_distance(word, b) <= SAME_WORD_MAX_DISTANCE) for b in brand_words):
            continue
        if word in NEUTRAL_WORDS and word not in GENDER_WORDS and word != "the":
            continue
        kept.append(token.strip(",()") if not token.isupper() else token.strip(",()").title())
    return " ".join(kept) if [w for w in kept if w.lower() != "the"] else ""


@dataclass
class Plan:
    # listing index -> (status, product key or None, confidence)
    status: dict[int, tuple[str, tuple | None, float | None]]
    products: dict[tuple, dict]      # product key -> attributes
    fragrances: dict[tuple, dict]    # identity key -> attributes
    review: list[Decision]
    stats: Counter


def build_plan(listings: list[Listing], decisions: list[Decision]) -> Plan:
    accepted = one_to_one(listings, decisions)
    groups: list[list[int]] = match_groups(listings, accepted)
    confidence: dict[int, float] = {}
    for decision in accepted:  # a listing matched in several pairs keeps its most similar one
        for index in (decision.a, decision.b):
            confidence[index] = max(confidence.get(index, 0.0), decision.similarity)
    matched = set(confidence)
    # An open review does not hide a listing: an unmatched listing becomes its
    # own product (visible) and its most similar review pair goes to the review
    # queue. If a human labels the pair "same", the next run merges them and
    # the product keeps its ID (assign_product_ids).
    best_review: dict[int, Decision] = {}
    for decision in decisions:
        if decision.kind != "review":
            continue
        for index in (decision.a, decision.b):
            if index not in matched and (index not in best_review or decision.similarity > best_review[index].similarity):
                best_review[index] = decision
    groups += [[i] for i in range(len(listings)) if i not in matched]

    stats: Counter = Counter()
    status: dict[int, tuple[str, tuple | None, float | None]] = {}
    products: dict[tuple, dict] = {}
    fragrances: dict[tuple, dict] = {}
    by_key: dict[tuple, list[list[int]]] = {}  # product key -> the groups that have it, in group order
    for group in groups:
        members = [listings[i] for i in group]
        volume = next((m.volume_ml for m in members if m.volume_ml), None)
        if volume is None:  # a product needs a size: leave it for review
            for i in group:
                status[i] = ("pending", None, None)
            stats["pending_no_volume"] += len(group)
            continue
        concentration = next((m.concentration for m in members if m.concentration), None)
        identity = identity_key(members[0].brand, members[0].name, members[0].store)
        presentation = "travel_set" if is_set(members[0].name) else "full_bottle"
        by_key.setdefault((identity, concentration, volume, presentation), []).append(group)
    apart = frozenset(frozenset((d.a, d.b)) for d in decisions if d.reason == "human_different")
    for (identity, concentration, volume, presentation), key_groups in by_key.items():
        parts = _split_by_store_words(listings, key_groups, identity, apart)
        stats["kept_apart_within_store"] += len(parts) - 1
        for part_identity, part_groups in parts:
            stats["merged_by_identical_key"] += sum(len(g) for g in part_groups[1:])
            part = [i for g in part_groups for i in g]
            members = [listings[i] for i in part]
            product_key = (part_identity, concentration, volume, presentation)
            fragrance = fragrances.setdefault(part_identity, {"listings": [], "genders": []})
            fragrance["listings"] += part
            fragrance["genders"] += [gender(m.brand, m.name) for m in members]
            product = products.setdefault(product_key, {"identity": part_identity, "concentration": concentration,
                                                        "volume_ml": volume, "presentation": presentation,
                                                        "listings": []})
            product["listings"] += part
    # A product sold by two or more stores is "matched" for all its listings,
    # including a store's own duplicate listing of it; otherwise "new_product".
    for product_key, product in products.items():
        state = "matched" if len({listings[i].store for i in product["listings"]}) > 1 else "new_product"
        for i in product["listings"]:
            status[i] = (state, product_key, confidence.get(i))
        stats[state] += len(product["listings"])
    stats["in_review_queue"] = len(best_review)  # listings with an open review pair (visible meanwhile)

    # One spelling per brand across the catalog, not per fragrance.
    brand_spellings: dict[str, list[str | None]] = defaultdict(list)
    for listing in listings:
        brand_spellings[identity_key(listing.brand, "")[0]].append(listing.brand)
    for identity, fragrance in fragrances.items():
        members = [listings[i] for i in fragrance["listings"]]
        fragrance["brand"] = display_brand(brand_spellings[identity[0]])
        # Prefer a name without store abbreviations ("Asad M.EDP SP100M"), not all caps, then the
        # spelling most listings use ("Titanio" 2, "Titaneo" 1), then the most descriptive.
        brand = fragrance["brand"]
        shown = {m.id: display_name(m.brand, m.name, brand) for m in members}
        spelled = Counter(name.lower() for name in shown.values() if name)
        reference = min(members, key=lambda m: (not shown[m.id], bool(ABBREVIATED.search(m.name)), m.name.isupper(),
                                                -spelled[shown[m.id].lower()], -len(shown[m.id]), m.name, m.id))
        # A generic name ("Perfume Shakira 50 ml") shows nothing beyond the brand: the brand is the name.
        fragrance["name"] = shown[reference.id] or brand
        # The identity's gender (its words, and store codes such as "(M)"/"(H)"); without one,
        # "unisex", which in this schema also means "not stated". Taking another member's words
        # instead made a gender-less identity print exactly like the gendered one.
        fragrance["gender"] = identity[2] or "unisex"
        vector = np.mean([m.embedding for m in members], axis=0)
        fragrance["embedding"] = vector / np.linalg.norm(vector)
    presentations: dict[tuple, set[str]] = defaultdict(set)
    for product in products.values():
        presentations[product["identity"]].add(product["presentation"])
    sets_only = {identity for identity, kinds in presentations.items() if kinds == {"travel_set"}}
    _disambiguate_fragrance_names(fragrances, stats, sets_only)
    review = sorted({d for i, d in best_review.items()}, key=lambda d: -d.similarity)
    return Plan(status, products, fragrances, review, stats)


def _distinguishing_label(identity: tuple, first: tuple, sets_only: set[tuple]) -> str | None:
    """What tells identity apart from first, the one that keeps the plain name."""
    own = sorted(set(identity[1]) - set(first[1]))
    if own:
        return " ".join(own)                    # "Ur Way (parfum)"
    if identity[3]:
        return " ".join(sorted(identity[3]))    # its edition numbers: "212 Vip Black (212)"
    if identity in sets_only and first not in sets_only:
        return "estuche"                        # a set whose name drops the numbers (they are sizes)
    missing = sorted(set(first[1]) - set(identity[1])) + sorted(first[3] - identity[3])
    return f"sin {' '.join(missing)}" if missing else None


def _disambiguate_fragrance_names(fragrances: dict[tuple, dict], stats: Counter,
                                  sets_only: set[tuple] = frozenset()) -> None:
    """(brand, name, gender) is UNIQUE in the schema; different identities can print alike.

    Nothing here depends on the order of the catalog: among identities that
    print alike, the one with the most listings keeps the name (then the one
    with the fewest words, and the smallest serialized only as a last resort),
    and each other one says what tells it apart: its own words ("Ur Way
    (parfum)"), else its edition numbers, else "estuche" (a set of the other's
    fragrance), else what it lacks ("sin parfum"). Only when nothing tells them
    apart, a short code computed from the identity itself (SHA-1: the same in
    every run while the fragrance does not change; it used to be a running
    count of the catalog, "(881)").
    """
    by_slot: dict[tuple, list[tuple]] = defaultdict(list)
    for identity, fragrance in fragrances.items():
        by_slot[(fragrance["brand"].lower(), fragrance["name"].lower(), fragrance["gender"])].append(identity)
    taken = set(by_slot)
    for (brand, _, gender_), identities in sorted(by_slot.items()):
        if len(identities) < 2:
            continue
        first, *others = sorted(identities, key=lambda identity: (
            -len(fragrances[identity]["listings"]), len(identity[1]), serialize_identity(identity)))
        for identity in others:
            fragrance = fragrances[identity]
            extra = _distinguishing_label(identity, first, sets_only)
            name = f"{fragrance['name']} ({extra})" if extra else None
            if name is None or (brand, name.lower(), gender_) in taken:
                code = hashlib.sha1(serialize_identity(identity).encode()).hexdigest()[:4]
                name = f"{fragrance['name']} ({code})"
            fragrance["name"] = name
            taken.add((brand, name.lower(), gender_))
            stats["fragrance_names_disambiguated"] += 1


def canonical_name(brand: str, fragrance: str, concentration: str | None, volume_ml: int, presentation: str) -> str:
    if fragrance.strip().lower() == brand.strip().lower():  # the brand is the name: "Agua Brava EDC 100 ml"
        fragrance = ""
    parts = [brand, fragrance, CONCENTRATION_LABELS.get(concentration or "", ""), f"{volume_ml} ml"]
    name = " ".join(part for part in parts if part)
    return f"{name} (set)" if presentation == "travel_set" else name


# --------------------------------------------------------------- database I/O


def load_listings(connection: psycopg.Connection, stores: tuple[str, ...] = MATCHING_STORES) -> list[Listing]:
    """Active, embedded listings of the matching stores. write_plan only touches these.

    Names and brands are repaired of mojibake here, so matching, fragrance identity
    and the canonical name all see the text the store meant (raw_listings keeps it as read).
    A gender the store declares apart from the name (dperfumes) is appended as the
    store's code (with_declared_gender), which the rules read like Beauty Perfumes'.
    """
    rows = connection.execute(
        """SELECT rl.raw_listing_id::text, s.name, rl.raw_brand, rl.raw_name, rl.parsed_volume_ml,
                  rl.parsed_concentration::text, rl.listing_url, rl.embedding::text, rl.declared_gender::text
           FROM raw_listings rl JOIN stores s USING (store_id)
           WHERE rl.is_active AND rl.embedding IS NOT NULL AND s.name = ANY(%s)
           ORDER BY s.name, rl.raw_listing_id""",
        (list(stores),),
    ).fetchall()
    return [
        Listing(id, store, brand and repair_mojibake(brand),
                with_declared_gender(repair_mojibake(name), declared_gender), volume, concentration, url,
                np.array([float(x) for x in vector.strip("[]").split(",")], dtype=np.float32))
        for id, store, brand, name, volume, concentration, url, vector, declared_gender in rows
    ]


def serialize_identity(identity: tuple) -> str:
    """fragrances.identity_key: "brand|core words|gender|edition numbers"."""
    brand, core, gender_, editions = identity
    return "|".join([brand, " ".join(core), gender_ or "", " ".join(sorted(editions))])


# The WHERE clauses skip no-op updates, so updated_at only moves when something
# changed. A skipped update returns no row, hence the SELECT fallbacks.
UPSERT_FRAGRANCE = """
INSERT INTO fragrances (identity_key, brand, name, gender, embedding)
VALUES (%(key)s, %(brand)s, %(name)s, %(gender)s::gender_type, %(embedding)s::vector)
ON CONFLICT (identity_key) DO UPDATE
SET brand = EXCLUDED.brand, name = EXCLUDED.name, gender = EXCLUDED.gender, embedding = EXCLUDED.embedding
WHERE (fragrances.brand, fragrances.name, fragrances.gender, fragrances.embedding)
      IS DISTINCT FROM (EXCLUDED.brand, EXCLUDED.name, EXCLUDED.gender, EXCLUDED.embedding)
RETURNING fragrance_id
"""
SELECT_FRAGRANCE = "SELECT fragrance_id FROM fragrances WHERE identity_key = %(key)s"

UPSERT_PRODUCT = """
INSERT INTO products (fragrance_id, concentration, volume_ml, presentation, canonical_name)
VALUES (%(fragrance_id)s, %(concentration)s::concentration_type, %(volume_ml)s,
        %(presentation)s::presentation_type, %(canonical_name)s)
ON CONFLICT ON CONSTRAINT products_fragrance_id_concentration_volume_ml_presentation_key DO UPDATE
SET canonical_name = EXCLUDED.canonical_name
WHERE products.canonical_name IS DISTINCT FROM EXCLUDED.canonical_name
RETURNING product_id
"""
SELECT_PRODUCT = """
SELECT product_id FROM products
WHERE fragrance_id = %(fragrance_id)s AND concentration IS NOT DISTINCT FROM %(concentration)s::concentration_type
  AND volume_ml = %(volume_ml)s AND presentation = %(presentation)s::presentation_type
"""


# Sets a product row's key (and name) to its plan product's; skipped when nothing changes.
REKEY_PRODUCT = """
UPDATE products
SET fragrance_id = %(fragrance_id)s, concentration = %(concentration)s::concentration_type,
    volume_ml = %(volume_ml)s, presentation = %(presentation)s::presentation_type,
    canonical_name = %(canonical_name)s
WHERE product_id = %(product_id)s
  AND (fragrance_id, concentration, volume_ml, presentation, canonical_name)
      IS DISTINCT FROM (%(fragrance_id)s, %(concentration)s::concentration_type, %(volume_ml)s,
                        %(presentation)s::presentation_type, %(canonical_name)s)
"""
EXISTING_PRODUCTS = """
SELECT p.product_id, f.identity_key, p.concentration::text, p.volume_ml, p.presentation::text, p.created_at
FROM products p JOIN fragrances f ON f.fragrance_id = p.fragrance_id
"""
# The unique key of products is not deferrable, so two rows cannot swap keys in
# one UPDATE each: write_plan first parks every row that changes key (or gives
# its key up) at volume_ml = PARKED_VOLUME + n, a size no real product has
# (volume_ml > 0 is the only check), and then sets the final keys; all in the
# plan's single transaction, so a parked row is never visible outside it.
PARKED_VOLUME = 1_000_000_000


def product_row_key(product: dict) -> tuple:
    """What identifies a products row: (fragrances.identity_key, concentration, volume_ml, presentation)."""
    return (serialize_identity(product["identity"]), product["concentration"], product["volume_ml"],
            product["presentation"])


@dataclass
class Assignment:
    ids: dict[tuple, object]        # plan product key -> the existing product_id it keeps (missing: a new row)
    displaced: dict[object, tuple]  # product_id -> plan key it gives up; its other listings go to that key's product
    stats: Counter                  # fusions, splits, swaps, rekeyed, reused_by_key, new


def _preferences(parts: dict[tuple, list[int]], own: tuple | None) -> list[tuple]:
    """The plan products an old product would keep its ID with, best first (the split rule).

    parts: plan key -> [listings, price readings] of the old product's listings in it.
    The part with the product's own key keeps the ID unless another part has
    strictly more price history; without its own key, the part with the most
    listings, then the most history. Ties: the key, so the order is the same every run.
    """
    if own in parts:
        others = sorted((key for key in parts if key != own), key=lambda key: (-parts[key][1], repr(key)))
        if others and parts[others[0]][1] > parts[own][1]:
            return [others[0], own] + others[1:]
        return [own] + others
    return sorted(parts, key=lambda key: (-parts[key][0], -parts[key][1], repr(key)))


def assign_product_ids(
    plan_listings: dict[tuple, list[str]],
    existing: dict[tuple, object],
    previous: dict[str, object],
    history: dict[str, int] | None = None,
    created: dict[object, object] | None = None,
) -> Assignment:
    """Which existing product_id each plan product keeps: listings first, then the key.

    plan_listings: product row key -> IDs of its listings in this run.
    existing: product row key -> product_id already in the database.
    previous: listing ID -> product_id it pointed to before this run (every listing, active or not).
    history: listing ID -> price readings it has (missing = 0).
    created: product_id -> products.created_at (fusion ties: the oldest).

    1. A product_id stays with the plan product that has its listings: the
       part chosen by the split rule (see _preferences) when they are now in
       several. An ID never goes to a plan product without any of its listings.
    2. Fusion: when the listings of several products are now one plan product,
       it keeps the ID with the most price history (all its listings, active
       or not), then the oldest (created_at), then the lowest ID. Another ID
       goes on to its next part, if it has one; else it is left (its row is
       deleted when no listing points to it, as before).
    3. Only then the key: a plan product that kept no ID reuses the row that
       has its key, if no listing of this run pointed to that row (a product
       that comes back after being out of every store). Otherwise it gets a
       new row.

    A row whose key a plan product needs but that keeps no plan product of its
    own (it has only inactive or pending listings left) is "displaced": write_plan
    moves those listings to the product that now has the key, as the old
    key-first rule did by giving it that row.

    The assignment is a stable matching (old products propose, plan products
    keep the best by rule 2), so it does not depend on the order of the catalog.
    """
    history = history or {}
    created = created or {}
    own_key = {old: key for key, old in existing.items()}
    product_history: Counter = Counter()
    for listing_id, old in previous.items():
        product_history[old] += history.get(listing_id, 0)
    parts: dict[object, dict[tuple, list[int]]] = defaultdict(dict)
    sources: dict[tuple, set] = defaultdict(set)
    for key, listing_ids in plan_listings.items():
        for listing_id in listing_ids:
            old = previous.get(listing_id)
            if old is not None:
                part = parts[old].setdefault(key, [0, 0])
                part[0] += 1
                part[1] += history.get(listing_id, 0)
                sources[key].add(old)

    def rank(old) -> tuple:  # lower is better: most history, then oldest, then lowest ID
        when = created.get(old)
        return (-product_history[old], when is None, when if when is not None else 0, str(old))

    preferences = {old: _preferences(old_parts, own_key.get(old)) for old, old_parts in parts.items()}
    holder: dict[tuple, object] = {}
    proposals = {old: 0 for old in preferences}
    waiting = sorted(preferences, key=str)
    while waiting:
        old = waiting.pop()
        if proposals[old] >= len(preferences[old]):
            continue  # every part it had went to another ID
        key = preferences[old][proposals[old]]
        proposals[old] += 1
        current = holder.get(key)
        if current is None:
            holder[key] = old
        elif rank(old) < rank(current):
            holder[key] = old
            waiting.append(current)
        else:
            waiting.append(old)

    ids = dict(holder)
    stats: Counter = Counter()
    assigned = set(ids.values())
    for key in plan_listings:
        if key in ids:
            continue
        row = existing.get(key)
        if row is not None and row not in assigned and row not in parts:
            ids[key] = row
            assigned.add(row)
            stats["reused_by_key"] += 1
        else:
            stats["new"] += 1
    displaced = {old: key for key, old in existing.items()
                 if key in plan_listings and old not in assigned}

    stats["fusions"] = sum(1 for olds in sources.values() if len(olds) > 1)
    stats["splits"] = sum(1 for old_parts in parts.values() if len(old_parts) > 1)
    # an ID now on a plan product without any of its listings, while they are on another: 0 by rule 1
    stats["swaps"] = sum(1 for key, old in ids.items() if old in parts and key not in parts[old])
    stats["rekeyed"] = sum(1 for key, old in ids.items() if own_key.get(old) != key)
    stats["displaced"] = len(displaced)
    return Assignment(ids, displaced, stats)


def _upsert(cursor: psycopg.Cursor, upsert: str, select: str, params: dict):
    cursor.execute(upsert, params)
    row = cursor.fetchone() or cursor.execute(select, params).fetchone()
    return row[0]


RECORD_RETIRED = """
INSERT INTO retired_products (product_id, replaced_by, reason, canonical_name)
VALUES (%(product_id)s, %(replaced_by)s, %(reason)s, %(canonical_name)s)
ON CONFLICT (product_id) DO UPDATE SET replaced_by = EXCLUDED.replaced_by, reason = EXCLUDED.reason,
    canonical_name = EXCLUDED.canonical_name, retired_at = now()
"""


def retired_destination(listings_before: list[str], now: dict[str, object], history: dict[str, int],
                        retired: object) -> object | None:
    """Where a product's listings went: the product holding most of them now (then most price history).

    listings_before: the IDs of the listings that pointed to the retired product before this run;
    now: listing ID -> its product after this run. None when none of them is in a product.
    """
    votes: dict[object, list[int]] = {}
    for listing_id in listings_before:
        product = now.get(listing_id)
        if product is not None and product != retired:
            vote = votes.setdefault(product, [0, 0])
            vote[0] += 1
            vote[1] += history.get(listing_id, 0)
    return max(votes, key=lambda product: (votes[product], str(product))) if votes else None


def _record_retired(cursor: psycopg.Cursor, previous: dict[str, object], history: dict[str, int]) -> int:
    """Record in retired_products (database/007) the products about to be deleted and where their listings went."""
    gone = dict(cursor.execute("""SELECT p.product_id, p.canonical_name FROM products p
                                  WHERE NOT EXISTS (SELECT 1 FROM raw_listings rl
                                                    WHERE rl.product_id = p.product_id)""").fetchall())
    if not gone:
        return 0
    before: dict[object, list[str]] = defaultdict(list)
    for listing_id, product in previous.items():
        if product in gone:
            before[product].append(listing_id)
    now = dict(cursor.execute("SELECT raw_listing_id::text, product_id FROM raw_listings WHERE raw_listing_id = "
                              "ANY(%s::uuid[])", ([l for ls in before.values() for l in ls],)).fetchall())
    rows = []
    for product, name in gone.items():
        destination = retired_destination(before.get(product, []), now, history, product)
        rows.append({"product_id": product, "replaced_by": destination, "canonical_name": name,
                     "reason": "merged" if destination is not None else "no_listings"})
    cursor.executemany(RECORD_RETIRED, rows)
    logger.info("product IDs retired: %d (%d merged into another)", len(rows),
                sum(1 for row in rows if row["replaced_by"] is not None))
    return len(rows)


def write_plan(connection: psycopg.Connection, listings: list[Listing], plan: Plan) -> Counter:
    """Upsert fragrances/products so their IDs survive re-runs; human decisions live in data/labeled.

    A product keeps the ID its listings had, even when its key changes; the
    row's key (its fragrance, concentration, size, presentation) is updated
    instead (see assign_product_ids). Only the listings loaded in this run are
    reassigned: inactive listings keep their product, and with it their price
    history, except those of a displaced row, which follow its key. Pending
    listings also keep their last product, so product_id no longer implies a
    resolved listing: read matching_status too. Products left without any
    listing, and fragrances left without products, are deleted; a deleted
    product's ID is recorded in retired_products with the product its
    listings went to (database/007), so the API can redirect saved links.

    Everything is one transaction. Rows that change key are parked first (see
    PARKED_VOLUME), so two rows can swap keys without breaking the unique key.

    Fails closed: a plan with a fragrance without a name is not written at
    all (nothing changes in the database). Returns the assignment's counts.
    """
    unnamed = [serialize_identity(identity) for identity, fragrance in plan.fragrances.items()
               if not (fragrance.get("name") or "").strip()]
    if unnamed:
        raise ValueError(f"refusing to write the plan: {len(unnamed)} fragrances without a name, "
                         f"e.g. {unnamed[:5]}")
    with connection.transaction(), connection.cursor() as cursor:
        rows = cursor.execute(EXISTING_PRODUCTS).fetchall()
        existing = {tuple(row[1:5]): row[0] for row in rows}
        own_key = {row[0]: tuple(row[1:5]) for row in rows}
        previous = dict(cursor.execute(
            "SELECT raw_listing_id::text, product_id FROM raw_listings WHERE product_id IS NOT NULL").fetchall())
        history = dict(cursor.execute(
            "SELECT raw_listing_id::text, count(*) FROM price_history GROUP BY raw_listing_id").fetchall())
        assignment = assign_product_ids(
            {product_row_key(product): [listings[i].id for i in product["listings"]]
             for product in plan.products.values()},
            existing, previous, history, {row[0]: row[5] for row in rows},
        )
        fragrance_ids = {}
        for identity, fragrance in plan.fragrances.items():
            fragrance_ids[identity] = _upsert(cursor, UPSERT_FRAGRANCE, SELECT_FRAGRANCE, {
                "key": serialize_identity(identity), "brand": fragrance["brand"], "name": fragrance["name"],
                "gender": fragrance["gender"],
                "embedding": "[" + ",".join(f"{x:.7f}" for x in fragrance["embedding"]) + "]",
            })
        # Phase 1: park every row that leaves its key, so no final key below is still taken.
        leaving = sorted({old for key, old in assignment.ids.items() if own_key[old] != key}
                         | set(assignment.displaced), key=str)
        cursor.executemany("UPDATE products SET volume_ml = %s WHERE product_id = %s",
                           [(PARKED_VOLUME + n, old) for n, old in enumerate(leaving)])
        # Phase 2: each plan product's row gets its key; new rows only after that.
        product_ids = {}
        for key, product in sorted(plan.products.items(),
                                   key=lambda item: product_row_key(item[1]) not in assignment.ids):
            fragrance = plan.fragrances[product["identity"]]
            params = {
                "fragrance_id": fragrance_ids[product["identity"]], "concentration": product["concentration"],
                "volume_ml": product["volume_ml"], "presentation": product["presentation"],
                "canonical_name": canonical_name(fragrance["brand"], fragrance["name"], product["concentration"],
                                                 product["volume_ml"], product["presentation"]),
            }
            old_id = assignment.ids.get(product_row_key(product))
            if old_id is not None:
                cursor.execute(REKEY_PRODUCT, {**params, "product_id": old_id})
                product_ids[key] = old_id
            else:
                product_ids[key] = _upsert(cursor, UPSERT_PRODUCT, SELECT_PRODUCT, params)
        # Resolved listings (matched / new_product) get their product. Pending
        # ones have none in the plan (None) and keep the one they had, so they
        # can inherit it when resolved; the API ignores pending listings.
        cursor.executemany(
            """UPDATE raw_listings SET product_id = COALESCE(%s, product_id), matching_status = %s::matching_status,
                   match_confidence = %s WHERE raw_listing_id = %s""",
            [(product_ids.get(key), state, round(conf, 3) if conf is not None else None, listings[i].id)
             for i, (state, key, conf) in plan.status.items()],
        )
        # A displaced row's remaining listings (inactive, pending) go to the product that has its key now.
        keyed = {product_row_key(product): product_ids[key] for key, product in plan.products.items()}
        cursor.executemany("UPDATE raw_listings SET product_id = %s WHERE product_id = %s",
                           [(keyed[key], old) for old, key in assignment.displaced.items()])
        assignment.stats["retired"] = _record_retired(cursor, previous, history)
        cursor.execute("""DELETE FROM products p
                          WHERE NOT EXISTS (SELECT 1 FROM raw_listings rl WHERE rl.product_id = p.product_id)""")
        cursor.execute("""DELETE FROM fragrances f
                          WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.fragrance_id = f.fragrance_id)""")
        parked = cursor.execute("SELECT count(*) FROM products WHERE volume_ml >= %s", (PARKED_VOLUME,)).fetchone()[0]
        if parked:  # cannot happen: every parked row gets a key or loses its listings; never commit one
            raise RuntimeError(f"refusing to write the plan: {parked} products left with a parked key")
    if assignment.stats["swaps"]:
        logger.warning("product IDs: %d moved to a product without any of their listings", assignment.stats["swaps"])
    return assignment.stats


# Side "a" of a pair is the store that comes first here (then alphabetical),
# so every CSV lists the same store pair the same way.
STORE_ORDER = ("preunic", "maicao", "salcobrand", "beautyperfumes")
REVIEW_COLUMNS = ["similarity", "reason", "store_a", "store_b", "name_a", "name_b", "volume_ml_a", "volume_ml_b",
                  "concentration_a", "concentration_b", "label", "reviewer_note", "url_a", "url_b"]


def store_rank(store: str) -> tuple[int, str]:
    return (STORE_ORDER.index(store) if store in STORE_ORDER else len(STORE_ORDER), store)


def ordered_pair(a: Listing, b: Listing) -> tuple[Listing, Listing]:
    return (a, b) if store_rank(a.store) <= store_rank(b.store) else (b, a)


def export_review_queue(listings: list[Listing], plan: Plan, directory: Path = REVIEW_DIRECTORY) -> Path:
    """Pairs for human review, in the store-neutral format load_overrides reads."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"review_queue_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(REVIEW_COLUMNS)
        for d in plan.review:
            a, b = ordered_pair(listings[d.a], listings[d.b])
            writer.writerow([f"{d.similarity:.3f}", d.reason, a.store, b.store, a.name, b.name, a.volume_ml,
                             b.volume_ml, a.concentration, b.concentration, "", "", a.url, b.url])
    return path


def run_matching(connection: psycopg.Connection, *, use_overrides: bool = True, write: bool = True,
                 stores: tuple[str, ...] = MATCHING_STORES,
                 before_write: Callable[[], None] | None = None) -> dict:
    """Stages 1-5 over the loaded listings; with write, save the plan and export the review queue.

    before_write runs right before anything is written (the entry point's
    check of its database writer lock, after the ~1 minute of matching).
    """
    listings = load_listings(connection, stores)
    overrides = load_overrides() if use_overrides else {}
    decisions = decide(listings, overrides)
    plan = build_plan(listings, decisions)
    summary = {
        "listings": len(listings), "candidate_pairs": len(decisions), "human_labels": len(overrides),
        "decisions": dict(Counter(d.kind for d in decisions)),
        "reasons": dict(Counter(d.reason for d in decisions).most_common()),
        "listing_status": dict(plan.stats),
        "fragrances": len(plan.fragrances), "products": len(plan.products),
    }
    if write:
        if before_write is not None:
            before_write()
        summary["product_ids"] = dict(write_plan(connection, listings, plan))
        summary["review_queue"] = str(export_review_queue(listings, plan))
    return summary


def main() -> None:
    load_env_file()  # DATABASE_URL from ./.env, like the daily run
    parser = argparse.ArgumentParser(description="Match raw_listings across stores")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-overrides", action="store_true", help="ignore human labels in data/labeled")
    parser.add_argument("--stores", default=",".join(MATCHING_STORES),
                        help=f"comma-separated stores to match (default: {','.join(MATCHING_STORES)})")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()
    stores = tuple(store.strip() for store in args.stores.split(",") if store.strip())

    with writer_connection(args.database_url) as connection:
        lock = None
        if not args.dry_run:  # a dry run writes nothing: no lock needed
            try:
                lock = acquire_writer_lock(connection, f"pipeline {os.getcwd()}")
            except DatabaseBusy as error:
                raise SystemExit(str(error)) from error
        try:
            require_current_schema(connection)
        except SchemaNotUpToDate as error:
            raise SystemExit(str(error)) from error
        try:
            summary = run_matching(connection, use_overrides=not args.no_overrides, write=not args.dry_run,
                                   stores=stores, before_write=lock.check if lock else None)
        except LockLost as error:
            raise SystemExit(str(error)) from error
    print(f"{summary['listings']} listings, {summary['candidate_pairs']} candidate pairs, "
          f"{summary['human_labels']} human labels loaded")
    print("decisions:", summary["decisions"])
    print("reasons:  ", summary["reasons"])
    print("listings: ", summary["listing_status"])
    print(f"canonical: {summary['fragrances']} fragrances, {summary['products']} products")
    if "product_ids" in summary:
        print("product ids:", summary["product_ids"])
    if "review_queue" in summary:
        print("review queue:", summary["review_queue"])


if __name__ == "__main__":
    main()
