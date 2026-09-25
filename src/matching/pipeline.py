"""Cross-store matching: candidates -> vetoes -> decision -> one-to-one -> canonical rows.

Usage:
    python -m src.matching.pipeline              # rebuild fragrances/products, export review queue
    python -m src.matching.pipeline --dry-run    # print the plan, write nothing
    python -m src.matching.pipeline --no-overrides

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
4. One-to-one: auto pairs are accepted by descending similarity, each listing
   at most once per other store.
5. Canonical rows: matched pairs and unmatched listings with a known volume
   become products; products that share brand, name core, gender and edition
   number share a fragrance.

Human labels in data/labeled/*.csv override the rules for the pairs they
cover ("same" -> match, "different" -> veto, other labels -> review).
"""

from __future__ import annotations

import argparse
import csv
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
    same_brand,
    same_name,
    veto,
    word_distance,
)
from src.scrapers.volume import VOLUME_PATTERN

TOP_K = 5
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
    pairs: dict[tuple[int, int], float] = {}
    for store, members in by_store.items():
        for other_store, others in by_store.items():
            if other_store == store:
                continue
            similarity = vectors[members] @ vectors[others].T
            for row, a in enumerate(members):
                ranked = [others[col] for col in np.argsort(-similarity[row])
                          if same_brand(listings[a].brand, listings[others[col]].brand)][:top_k]
                for b in ranked:
                    pairs[(min(a, b), max(a, b))] = float(vectors[a] @ vectors[b])
    return [(a, b, s) for (a, b), s in pairs.items()]


def classify(a: Listing, b: Listing, genders: GenderIndex) -> tuple[str, str]:
    """Stage 2 and 3 for one pair: ("veto"|"auto"|"review", reason)."""
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


def load_overrides(directory: Path = LABELED_DIRECTORY) -> dict[frozenset[str], str]:
    """Human labels keyed by the pair of listing URLs."""
    overrides: dict[frozenset[str], str] = {}
    for path in sorted(directory.glob("*.csv")):
        for row in csv.DictReader(path.open(encoding="utf-8")):
            label = (row.get("label") or "").strip()
            if label and row.get("preunic_url") and row.get("maicao_url"):
                overrides[frozenset((row["preunic_url"], row["maicao_url"]))] = label
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
            kind, reason = classify(listings[a], listings[b], genders)
        decisions.append(Decision(a, b, similarity, kind, reason))
    return decisions


# ------------------------------------------------------------------ stage 4


def one_to_one(listings: list[Listing], decisions: list[Decision]) -> list[Decision]:
    """Accept auto pairs by descending similarity; each listing once per other store."""
    taken: set[tuple[int, str]] = set()
    accepted = []
    for decision in sorted((d for d in decisions if d.kind == "auto"), key=lambda d: -d.similarity):
        slot_a = (decision.a, listings[decision.b].store)
        slot_b = (decision.b, listings[decision.a].store)
        if slot_a in taken or slot_b in taken:
            continue
        taken |= {slot_a, slot_b}
        accepted.append(decision)
    return accepted


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
    groups: list[list[int]] = [[d.a, d.b] for d in accepted]
    confidence = {i: d.similarity for d in accepted for i in (d.a, d.b)}
    matched = set(confidence)
    best_review: dict[int, Decision] = {}
    for decision in decisions:
        if decision.kind != "review":
            continue
        for index in (decision.a, decision.b):
            if index not in matched and (index not in best_review or decision.similarity > best_review[index].similarity):
                best_review[index] = decision
    groups += [[i] for i in range(len(listings)) if i not in matched and i not in best_review]

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
    for i, decision in best_review.items():
        status[i] = ("pending", None, decision.similarity)
    stats["pending_review"] = len(best_review)

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


def load_listings(connection: psycopg.Connection) -> list[Listing]:
    rows = connection.execute(
        """SELECT rl.raw_listing_id::text, s.name, rl.raw_brand, rl.raw_name, rl.parsed_volume_ml,
                  rl.parsed_concentration::text, rl.listing_url, rl.embedding::text
           FROM raw_listings rl JOIN stores s USING (store_id)
           WHERE rl.is_active AND rl.embedding IS NOT NULL
           ORDER BY s.name, rl.raw_listing_id"""
    ).fetchall()
    return [
        Listing(id, store, brand, name, volume, concentration, url,
                np.array([float(x) for x in vector.strip("[]").split(",")], dtype=np.float32))
        for id, store, brand, name, volume, concentration, url, vector in rows
    ]


def write_plan(connection: psycopg.Connection, listings: list[Listing], plan: Plan) -> None:
    """Rebuild fragrances/products from scratch; human decisions live in data/labeled."""
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute("UPDATE raw_listings SET product_id = NULL, matching_status = 'pending', match_confidence = NULL")
        cursor.execute("DELETE FROM products")
        cursor.execute("DELETE FROM fragrances")
        fragrance_ids = {}
        for identity, fragrance in plan.fragrances.items():
            cursor.execute(
                """INSERT INTO fragrances (brand, name, gender, embedding)
                   VALUES (%s, %s, %s::gender_type, %s::vector) RETURNING fragrance_id""",
                (fragrance["brand"], fragrance["name"], fragrance["gender"],
                 "[" + ",".join(f"{x:.7f}" for x in fragrance["embedding"]) + "]"),
            )
            fragrance_ids[identity] = cursor.fetchone()[0]
        product_ids = {}
        for key, product in plan.products.items():
            fragrance = plan.fragrances[product["identity"]]
            cursor.execute(
                """INSERT INTO products (fragrance_id, concentration, volume_ml, presentation, canonical_name)
                   VALUES (%s, %s::concentration_type, %s, %s::presentation_type, %s) RETURNING product_id""",
                (fragrance_ids[product["identity"]], product["concentration"], product["volume_ml"],
                 product["presentation"],
                 canonical_name(fragrance["brand"], fragrance["name"], product["concentration"],
                                product["volume_ml"], product["presentation"])),
            )
            product_ids[key] = cursor.fetchone()[0]
        cursor.executemany(
            """UPDATE raw_listings SET product_id = %s, matching_status = %s::matching_status,
                   match_confidence = %s WHERE raw_listing_id = %s""",
            [(product_ids.get(key), state, round(conf, 3) if conf is not None else None, listings[i].id)
             for i, (state, key, conf) in plan.status.items()],
        )


def export_review_queue(listings: list[Listing], plan: Plan, directory: Path = REVIEW_DIRECTORY) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"review_queue_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["similarity", "reason", "preunic_name", "maicao_name", "preunic_volume_ml",
                         "maicao_volume_ml", "preunic_concentration", "maicao_concentration",
                         "label", "reviewer_note", "preunic_url", "maicao_url"])
        for d in plan.review:
            p, m = sorted((listings[d.a], listings[d.b]), key=lambda x: x.store != "preunic")
            writer.writerow([f"{d.similarity:.3f}", d.reason, p.name, m.name, p.volume_ml, m.volume_ml,
                             p.concentration, m.concentration, "", "", p.url, m.url])
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Match raw_listings across stores")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-overrides", action="store_true", help="ignore human labels in data/labeled")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    with psycopg.connect(args.database_url) as connection:
        listings = load_listings(connection)
        overrides = {} if args.no_overrides else load_overrides()
        decisions = decide(listings, overrides)
        plan = build_plan(listings, decisions)
        print(f"{len(listings)} listings, {len(decisions)} candidate pairs, "
              f"{len(overrides)} human labels loaded")
        print("decisions:", dict(Counter(d.kind for d in decisions)))
        print("reasons:  ", dict(Counter(d.reason for d in decisions).most_common()))
        print("listings: ", dict(plan.stats))
        print(f"canonical: {len(plan.fragrances)} fragrances, {len(plan.products)} products")
        if args.dry_run:
            return
        write_plan(connection, listings, plan)
        print("review queue:", export_review_queue(listings, plan))


if __name__ == "__main__":
    main()
