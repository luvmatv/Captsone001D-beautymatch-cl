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
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import psycopg

from src.loader.raw_listings import DEFAULT_DATABASE_URL
from src.matching.rules import (
    DESCRIPTIVE_GENDER_WORDS,
    GENDER_WORDS,
    NEUTRAL_WORDS,
    SAME_WORD_MAX_DISTANCE,
    GenderIndex,
    gender,
    identity_key,
    is_set,
    marker_gender_conflict,
    name_with_gender_markers,
    same_brand,
    same_name,
    veto,
    word_distance,
)
from src.scrapers.volume import VOLUME_PATTERN

TOP_K = 5
# Stores the matching runs on. Other stores can be scraped and loaded (their
# price history accumulates) but their listings stay pending, with no
# product, until the rules are calibrated for them. Salcobrand joined after a
# labeled random sample: 30/30 correct with Preunic, 30/30 with Maicao.
MATCHING_STORES = ("preunic", "maicao", "salcobrand", "beautyperfumes")
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
                ranked = [others[col] for col in np.argsort(-similarity[row])
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
    """
    kind, reason = _classify_names(a, b, genders)
    if kind != "veto" and marked_genders is not None and marker_gender_conflict(
            (a.store, a.brand, a.name), (b.store, b.brand, b.name), marked_genders):
        return "review", "gender_marker"
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
    decisions = []
    for (a, b), similarity in pairs.items():
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
    return (identity_key(listing.brand, listing.name), listing.concentration, listing.volume_ml, presentation)


def _same_store_listings_agree(listings: list[Listing], members: list[int], stores: frozenset[str]) -> bool:
    """Listings of one store may share a group only if they are the same product
    (a store publishing it twice): exactly the same listing_key, nothing looser."""
    for store in stores:
        keys = {listing_key(listings[i]) for i in members if listings[i].store == store}
        if len(keys) != 1 or None in keys:
            return False
    return True


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
    for token in VOLUME_PATTERN.sub(" ", name).replace("+", " ").replace(" - ", " ").split():
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
    # the product keeps its ID (inherit_product_ids).
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
    for group in groups:
        members = [listings[i] for i in group]
        volume = next((m.volume_ml for m in members if m.volume_ml), None)
        if volume is None:  # a product needs a size: leave it for review
            for i in group:
                status[i] = ("pending", None, None)
            stats["pending_no_volume"] += len(group)
            continue
        concentration = next((m.concentration for m in members if m.concentration), None)
        identity = identity_key(members[0].brand, members[0].name)
        presentation = "travel_set" if is_set(members[0].name) else "full_bottle"
        product_key = (identity, concentration, volume, presentation)
        if product_key in products:
            stats["merged_by_identical_key"] += len(group)
        fragrance = fragrances.setdefault(identity, {"listings": [], "genders": []})
        fragrance["listings"] += group
        fragrance["genders"] += [gender(m.brand, m.name) for m in members]
        product = products.setdefault(product_key, {"identity": identity, "concentration": concentration,
                                                    "volume_ml": volume, "presentation": presentation,
                                                    "listings": []})
        product["listings"] += group
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
        # Prefer a name without store abbreviations ("Asad M.EDP SP100M"), not all caps, most descriptive.
        brand = fragrance["brand"]
        reference = min(members, key=lambda m: (not display_name(m.brand, m.name, brand),
                                                bool(ABBREVIATED.search(m.name)), m.name.isupper(),
                                                -len(display_name(m.brand, m.name, brand))))
        fragrance["name"] = display_name(reference.brand, reference.name, brand)
        fragrance["gender"] = next((g for g in fragrance["genders"] if g), "unisex")
        vector = np.mean([m.embedding for m in members], axis=0)
        fragrance["embedding"] = vector / np.linalg.norm(vector)
    _disambiguate_fragrance_names(fragrances, stats)
    review = sorted({d for i, d in best_review.items()}, key=lambda d: -d.similarity)
    return Plan(status, products, fragrances, review, stats)


def _disambiguate_fragrance_names(fragrances: dict[tuple, dict], stats: Counter) -> None:
    """(brand, name, gender) is UNIQUE in the schema; different identities can print alike."""
    seen: dict[tuple, tuple] = {}
    for identity, fragrance in fragrances.items():
        slot = (fragrance["brand"].lower(), fragrance["name"].lower(), fragrance["gender"])
        if slot in seen and seen[slot] != identity:
            extra = " ".join(sorted(set(identity[1]) - set(seen[slot][1]))) or " ".join(sorted(identity[3]))
            fragrance["name"] = f"{fragrance['name']} ({extra or len(seen)})"
            stats["fragrance_names_disambiguated"] += 1
            slot = (fragrance["brand"].lower(), fragrance["name"].lower(), fragrance["gender"])
        seen[slot] = identity


def canonical_name(brand: str, fragrance: str, concentration: str | None, volume_ml: int, presentation: str) -> str:
    parts = [brand, fragrance, CONCENTRATION_LABELS.get(concentration or "", ""), f"{volume_ml} ml"]
    name = " ".join(part for part in parts if part)
    return f"{name} (set)" if presentation == "travel_set" else name


# --------------------------------------------------------------- database I/O


def load_listings(connection: psycopg.Connection, stores: tuple[str, ...] = MATCHING_STORES) -> list[Listing]:
    """Active, embedded listings of the matching stores. write_plan only touches these."""
    rows = connection.execute(
        """SELECT rl.raw_listing_id::text, s.name, rl.raw_brand, rl.raw_name, rl.parsed_volume_ml,
                  rl.parsed_concentration::text, rl.listing_url, rl.embedding::text
           FROM raw_listings rl JOIN stores s USING (store_id)
           WHERE rl.is_active AND rl.embedding IS NOT NULL AND s.name = ANY(%s)
           ORDER BY s.name, rl.raw_listing_id""",
        (list(stores),),
    ).fetchall()
    return [
        Listing(id, store, brand, name, volume, concentration, url,
                np.array([float(x) for x in vector.strip("[]").split(",")], dtype=np.float32))
        for id, store, brand, name, volume, concentration, url, vector in rows
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


INHERIT_PRODUCT = """
UPDATE products
SET fragrance_id = %(fragrance_id)s, concentration = %(concentration)s::concentration_type,
    volume_ml = %(volume_ml)s, presentation = %(presentation)s::presentation_type,
    canonical_name = %(canonical_name)s
WHERE product_id = %(product_id)s
RETURNING product_id
"""
EXISTING_PRODUCTS = """
SELECT p.product_id, f.identity_key, p.concentration::text, p.volume_ml, p.presentation::text
FROM products p JOIN fragrances f ON f.fragrance_id = p.fragrance_id
"""


def product_row_key(product: dict) -> tuple:
    """What identifies a products row: (fragrances.identity_key, concentration, volume_ml, presentation)."""
    return (serialize_identity(product["identity"]), product["concentration"], product["volume_ml"],
            product["presentation"])


def inherit_product_ids(
    plan_listings: dict[tuple, list[str]],
    existing: dict[tuple, object],
    previous: dict[str, object],
) -> dict[tuple, object]:
    """Which plan products take over the ID of an existing product.

    plan_listings: product row key -> IDs of its listings in this run.
    existing: product row key -> product_id already in the database.
    previous: listing ID -> product_id it pointed to before this run.

    A plan product whose key is already in the database keeps that row (upsert).
    Otherwise it inherits the product most of its listings pointed to, unless
    another plan product claims that row by key. So a pair that loses the
    member its key came from, or a key changed by a rule change, keeps its ID.
    Each old product is inherited at most once; ties go to the lowest ID.
    """
    claimed = {existing[key] for key in plan_listings if key in existing}
    votes: Counter = Counter()
    for key, listing_ids in plan_listings.items():
        if key in existing:
            continue
        for listing_id in listing_ids:
            old = previous.get(listing_id)
            if old is not None and old not in claimed:
                votes[(key, old)] += 1
    inherited: dict[tuple, object] = {}
    for (key, old), _ in sorted(votes.items(), key=lambda vote: (-vote[1], str(vote[0][1]), repr(vote[0][0]))):
        if key not in inherited and old not in inherited.values():
            inherited[key] = old
    return inherited


def _upsert(cursor: psycopg.Cursor, upsert: str, select: str, params: dict):
    cursor.execute(upsert, params)
    row = cursor.fetchone() or cursor.execute(select, params).fetchone()
    return row[0]


def write_plan(connection: psycopg.Connection, listings: list[Listing], plan: Plan) -> None:
    """Upsert fragrances/products so their IDs survive re-runs; human decisions live in data/labeled.

    A product keeps its ID while its key is unchanged, and inherits the ID its
    listings had when the key changes (see inherit_product_ids). Only the
    listings loaded in this run are reassigned: inactive listings keep their
    product, and with it their price history. Pending listings also keep
    their last product, so product_id no longer implies a resolved listing:
    read matching_status too. Products left without any listing, and
    fragrances left without products, are deleted.
    """
    with connection.transaction(), connection.cursor() as cursor:
        existing = {tuple(row[1:]): row[0] for row in cursor.execute(EXISTING_PRODUCTS).fetchall()}
        previous = dict(cursor.execute(
            "SELECT raw_listing_id::text, product_id FROM raw_listings WHERE product_id IS NOT NULL").fetchall())
        inherited = inherit_product_ids(
            {product_row_key(product): [listings[i].id for i in product["listings"]]
             for product in plan.products.values()},
            existing, previous,
        )
        fragrance_ids = {}
        for identity, fragrance in plan.fragrances.items():
            fragrance_ids[identity] = _upsert(cursor, UPSERT_FRAGRANCE, SELECT_FRAGRANCE, {
                "key": serialize_identity(identity), "brand": fragrance["brand"], "name": fragrance["name"],
                "gender": fragrance["gender"],
                "embedding": "[" + ",".join(f"{x:.7f}" for x in fragrance["embedding"]) + "]",
            })
        product_ids = {}
        for key, product in plan.products.items():
            fragrance = plan.fragrances[product["identity"]]
            params = {
                "fragrance_id": fragrance_ids[product["identity"]], "concentration": product["concentration"],
                "volume_ml": product["volume_ml"], "presentation": product["presentation"],
                "canonical_name": canonical_name(fragrance["brand"], fragrance["name"], product["concentration"],
                                                 product["volume_ml"], product["presentation"]),
            }
            old_id = inherited.get(product_row_key(product))
            if old_id is not None:
                product_ids[key] = cursor.execute(INHERIT_PRODUCT, {**params, "product_id": old_id}).fetchone()[0]
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
        cursor.execute("""DELETE FROM products p
                          WHERE NOT EXISTS (SELECT 1 FROM raw_listings rl WHERE rl.product_id = p.product_id)""")
        cursor.execute("""DELETE FROM fragrances f
                          WHERE NOT EXISTS (SELECT 1 FROM products p WHERE p.fragrance_id = f.fragrance_id)""")


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
                 stores: tuple[str, ...] = MATCHING_STORES) -> dict:
    """Stages 1-5 over the loaded listings; with write, save the plan and export the review queue."""
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
        write_plan(connection, listings, plan)
        summary["review_queue"] = str(export_review_queue(listings, plan))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Match raw_listings across stores")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-overrides", action="store_true", help="ignore human labels in data/labeled")
    parser.add_argument("--stores", default=",".join(MATCHING_STORES),
                        help=f"comma-separated stores to match (default: {','.join(MATCHING_STORES)})")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()
    stores = tuple(store.strip() for store in args.stores.split(",") if store.strip())

    with psycopg.connect(args.database_url) as connection:
        summary = run_matching(connection, use_overrides=not args.no_overrides, write=not args.dry_run, stores=stores)
    print(f"{summary['listings']} listings, {summary['candidate_pairs']} candidate pairs, "
          f"{summary['human_labels']} human labels loaded")
    print("decisions:", summary["decisions"])
    print("reasons:  ", summary["reasons"])
    print("listings: ", summary["listing_status"])
    print(f"canonical: {summary['fragrances']} fragrances, {summary['products']} products")
    if "review_queue" in summary:
        print("review queue:", summary["review_queue"])


if __name__ == "__main__":
    main()
