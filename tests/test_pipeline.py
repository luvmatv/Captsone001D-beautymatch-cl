import csv

import numpy as np
import pytest

from src.matching import pipeline
from src.matching.pipeline import (
    Decision,
    Listing,
    build_plan,
    canonical_name,
    classify,
    decide,
    display_brand,
    display_name,
    REVIEW_COLUMNS,
    export_review_queue,
    inherit_product_ids,
    labeled_pair,
    load_overrides,
    match_groups,
    one_to_one,
    serialize_identity,
)
from src.matching.rules import identity_key
from src.matching.rules import GenderIndex, same_brand


def listing(n, store, brand, name, volume=None, concentration=None, vector=(1.0, 0.0)):
    v = np.array(vector, dtype=np.float32)
    return Listing(f"id{n}", store, brand, name, volume, concentration, f"https://{store}/{n}", v / np.linalg.norm(v))


GENDERS = GenderIndex([])


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (listing(1, "preunic", "Shakira", "Perfume Fucsia EDP 50 ml", 50, "edp"),
         listing(2, "maicao", "Etienne", "Perfume Fucsia EDP 50 ml", 50, "edp"), ("veto", "brand")),
        (listing(1, "preunic", "Shakira", "Fucsia EDP 50 ml", 50, "edp"),
         listing(2, "maicao", "SHAKIRA", "Fucsia EDP 80 ml", 80, "edp"), ("veto", "volume")),
        (listing(1, "preunic", "Shakira", "Fucsia EDP 50 ml", 50, "edp"),
         listing(2, "maicao", "SHAKIRA", "Fucsia EDT 50 ml", 50, "edt"), ("veto", "concentration")),
        (listing(1, "preunic", "Shakira", "EDP Shakira Fucsia Elixir 50 ml", 50, "edp"),
         listing(2, "maicao", "SHAKIRA", "Shakira Fucsia Elixir Edp 50Ml", 50, "edp"), ("auto", "same_name")),
        (listing(1, "preunic", "Antonio Banderas", "Eau de Toilette KING OF SEDUCTION", None, "edt"),
         listing(2, "maicao", "ANTONIO BANDERAS", "King Of Seduction Eau de Toilette 50 mL", 50, "edt"),
         ("review", "unknown_volume")),
        (listing(1, "preunic", "Ariana Grande", "Perfume Mujer Ariana Grande Cloud Pink EDP 30 Ml", 30, "edp"),
         listing(2, "maicao", "ARIANA GRANDE", "Ariana Grande Cloud EDP 30 ML", 30, "edp"), ("review", "extra_words")),
    ],
)
def test_classify(a, b, expected) -> None:
    assert classify(a, b, GENDERS) == expected


def test_a_store_gender_code_sends_an_accepted_pair_to_review_but_never_lifts_a_veto() -> None:
    # real listings: Beauty Perfumes' women's The Icon "(M)" and Preunic's unmarked men's The Icon
    items = [listing(0, "beautyperfumes", "Antonio Banderas", "ANTONIO BANDERAS THE ICON 100ML EDP (M)", 100, "edp"),
             listing(1, "preunic", "Antonio Banderas", "Antonio Banderas The Icon EDP 100 Ml", 100, "edp"),
             listing(2, "preunic", "Antonio Banderas", "Fragancia The Icon Femenino EDP 100 ML", 100, "edp",
                     vector=(0.0, 1.0))]
    decision = {(d.a, d.b): (d.kind, d.reason) for d in decide(items)}
    assert decision[(0, 1)] == ("review", "gender_marker")  # accepted by the name rules alone
    # without the catalog of codes, classify keeps the name rules' decision
    assert classify(items[0], items[1], GenderIndex([])) == ("auto", "same_name")
    # a veto stays a veto: a different volume is not reopened by the code
    other_size = listing(3, "preunic", "Antonio Banderas", "Antonio Banderas The Icon EDP 50 Ml", 50, "edp")
    marked = GenderIndex([("beautyperfumes", "Antonio Banderas", "ANTONIO BANDERAS THE ICON 100ML EDP mujer", 100, "edp"),
                          ("preunic", "Antonio Banderas", "Fragancia The Icon Femenino EDP 100 ML", 100, "edp"),
                          ("preunic", "Antonio Banderas", "Antonio Banderas The Icon EDP 100 Ml", 100, "edp")])
    assert classify(items[0], other_size, GenderIndex([]), marked) == ("veto", "volume")


def test_one_to_one_keeps_the_most_similar_pair_for_each_listing() -> None:
    items = [listing(0, "preunic", "X", "a"), listing(1, "maicao", "X", "a"), listing(2, "maicao", "X", "a")]
    decisions = [Decision(0, 1, 0.95, "auto", "same_name"), Decision(0, 2, 0.99, "auto", "same_name")]
    assert one_to_one(items, decisions) == [decisions[1]]


def test_three_stores_chain_into_one_product() -> None:
    items = [
        listing(0, "maicao", "SHAKIRA", "Shakira Fucsia Elixir Edp 50Ml", 50, "edp", (1, 0)),
        listing(1, "preunic", "Shakira", "EDP Shakira Fucsia Elixir 50 ml", 50, "edp", (1, 0.01)),
        listing(2, "salcobrand", "Shakira", "Perfume Shakira Fucsia Elixir EDP 50ml", 50, "edp", (1, 0.02)),
    ]
    decisions = [Decision(0, 1, 0.99, "auto", "same_name"), Decision(1, 2, 0.98, "auto", "same_name"),
                 Decision(0, 2, 0.97, "auto", "same_name")]
    assert len(one_to_one(items, decisions)) == 3        # the third pair only confirms the group
    assert match_groups(items, decisions) == [[0, 1, 2]]
    plan = build_plan(items, decisions)
    assert plan.status[0][1] == plan.status[1][1] == plan.status[2][1]  # one product
    assert {plan.status[i][0] for i in range(3)} == {"matched"}
    assert plan.status[2][2] == 0.98                      # its most similar pair


def test_a_chain_never_puts_two_listings_of_one_store_together() -> None:
    items = [listing(0, "preunic", "X", "a"), listing(1, "maicao", "X", "a"),
             listing(2, "salcobrand", "X", "a"), listing(3, "preunic", "X", "a")]
    decisions = [Decision(0, 1, 0.99, "auto", "same_name"), Decision(1, 2, 0.98, "auto", "same_name"),
                 Decision(2, 3, 0.97, "auto", "same_name")]  # would join preunic 0 and preunic 3
    assert one_to_one(items, decisions) == decisions[:2]
    assert match_groups(items, one_to_one(items, decisions)) == [[0, 1, 2]]


def test_a_chain_never_joins_a_pair_the_rules_vetoed() -> None:
    # Real listings: Salcobrand does not state the concentration, so it matches
    # both the Preunic "Colonia" and the Maicao "EDT"; that Preunic-Maicao pair
    # is vetoed by concentration and must stay apart.
    items = [
        listing(0, "preunic", "Agua Brava", "Colonia AGUA BRAVA de 100ml", 100, "cologne", (1, 0)),
        listing(1, "maicao", "AGUA BRAVA", "Hombre Edt Eau de Toilette de 100 mL", 100, "edt", (1, 0.01)),
        listing(2, "salcobrand", "Agua Brava", "Fragancia Agua Brava 100ml", 100, None, (1, 0.02)),
        listing(3, "preunic", "Agua Brava", "Colonia AGUA BRAVA C/VAP", 25, "cologne", (0.3, 1)),
        listing(4, "maicao", "AGUA BRAVA", "Edt Eau de Toilette de 25 mL", 25, "edt", (0.3, 1.01)),
        listing(5, "salcobrand", "Agua Brava", "Perfume Agua Brava 25ml", 25, None, (0.3, 1.02)),
    ]
    decisions = decide(items)
    kinds = {frozenset((d.a, d.b)): (d.kind, d.reason) for d in decisions}
    for p, m, s in ((0, 1, 2), (3, 4, 5)):
        assert kinds[frozenset((p, m))] == ("veto", "concentration")
        assert kinds[frozenset((p, s))][0] == kinds[frozenset((m, s))][0] == "auto"

    groups = match_groups(items, one_to_one(items, decisions))
    for p, m in ((0, 1), (3, 4)):
        assert not any(p in group and m in group for group in groups)
    plan = build_plan(items, decisions)
    assert plan.status[0][1] != plan.status[1][1] and plan.status[3][1] != plan.status[4][1]


ITZY = [  # real listings: Salcobrand lists each body splash twice, with two names
    listing(0, "preunic", "Itzy", "Body Splash Itzy Fantasy 250 ml", 250, None, (1, 0)),
    listing(1, "maicao", "ITZY", "Body Splash Fantasy 250 Ml", 250, None, (1, 0.01)),
    listing(2, "salcobrand", "Itzy", "Body Splash Itzy Fantasy 250 ml", 250, None, (1, 0.005)),
    listing(3, "salcobrand", "Itzy", "Body Splash Fantasy 250ml", 250, None, (1, 0.012)),
    listing(4, "preunic", "Itzy", "Body Splash Itzy Angel 250 ml", 250, None, (0, 1)),
    listing(5, "maicao", "ITZY", "Body Splash Angel 250 Ml", 250, None, (0.01, 1)),
    listing(6, "salcobrand", "Itzy", "Body Splash Itzy Angel 250 ml", 250, None, (0.005, 1)),
    listing(7, "salcobrand", "Itzy", "Body Splash Angel 250ml", 250, None, (0.012, 1)),
]


def test_a_store_duplicate_with_the_same_key_does_not_split_a_match() -> None:
    # Preunic pairs with one Salcobrand copy and Maicao with the other: the
    # copies have the same key, so the Preunic-Maicao match survives.
    groups = match_groups(ITZY, one_to_one(ITZY, decide(ITZY)))
    assert sorted(map(sorted, groups)) == [[0, 1, 2, 3], [4, 5, 6, 7]]
    plan = build_plan(ITZY, decide(ITZY))
    assert len({plan.status[i][1] for i in (0, 1, 2, 3)}) == 1
    assert len({plan.status[i][1] for i in (4, 5, 6, 7)}) == 1
    assert plan.status[0][1] != plan.status[4][1]            # Fantasy and Angel stay apart


@pytest.mark.parametrize(("volume", "name"), [
    (200, "Body Splash Fantasy 250ml"),          # another volume
    (250, "Body Splash Fantasy Glow 250ml"),     # another fragrance
    (None, "Body Splash Fantasy"),               # no volume: no key
])
def test_a_store_duplicate_needs_exactly_the_same_key(volume, name) -> None:
    items = ITZY[:3] + [listing(3, "salcobrand", "Itzy", name, volume, None, (1, 0.012))]
    decisions = [Decision(0, 2, 0.99, "auto", "same_name"), Decision(1, 3, 0.98, "auto", "same_name"),
                 Decision(0, 1, 0.97, "auto", "same_name")]
    groups = match_groups(items, one_to_one(items, decisions))
    assert not any(2 in group and 3 in group for group in groups)


def test_groups_keep_the_order_of_their_most_similar_pair() -> None:
    items = [listing(i, store, "X", "a") for i, store in enumerate(["preunic", "maicao", "preunic", "maicao"])]
    decisions = [Decision(0, 1, 0.90, "auto", "same_name"), Decision(2, 3, 0.95, "auto", "same_name")]
    assert match_groups(items, one_to_one(items, decisions)) == [[2, 3], [0, 1]]


def candidates_without_cache(listings, top_k):
    """candidates() as it was before same_brand was cached: one call per pair of listings."""
    by_store = {}
    for index, item in enumerate(listings):
        by_store.setdefault(item.store, []).append(index)
    vectors = np.stack([item.embedding for item in listings])
    pairs = {}
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


def test_candidates_compute_each_brand_pair_once_with_the_same_result(monkeypatch) -> None:
    # Brands as the stores write them: case, a substring ("Banderas"), a typo
    # ("Latafa") and a missing brand, which same_brand accepts against any brand.
    brands = ["Antonio Banderas", "ANTONIO BANDERAS", "Banderas", "Lattafa", "Latafa", "Shakira", None]
    rng = np.random.default_rng(0)
    items = [listing(i, store, brands[i % len(brands)], f"name {i}", vector=rng.normal(size=8))
             for i, store in enumerate(["preunic", "maicao", "salcobrand", "beautyperfumes"] * 15)]
    expected = candidates_without_cache(items, top_k=2)

    calls = []
    monkeypatch.setattr(pipeline, "same_brand", lambda a, b: calls.append((a, b)) or same_brand(a, b))
    result = pipeline.candidates(items, top_k=2)
    assert sorted(result) == sorted(expected)
    assert len(calls) == len(set(calls)) <= len(brands) ** 2


def test_labels_are_read_in_both_formats(tmp_path) -> None:
    (tmp_path / "old.csv").write_text(
        "pair_id,label,preunic_url,maicao_url\n1,same,https://p/1,https://m/1\n2,,https://p/2,https://m/2\n",
        encoding="utf-8")
    (tmp_path / "new.csv").write_text(
        "pair_id,store_a,store_b,label,url_a,url_b\n1,maicao,salcobrand,different,https://m/1,https://s/1\n",
        encoding="utf-8")
    assert load_overrides(tmp_path) == {
        frozenset(("https://p/1", "https://m/1")): "same",            # unlabeled rows are skipped
        frozenset(("https://s/1", "https://m/1")): "different",       # order does not matter
    }
    assert labeled_pair({"url_a": " https://a ", "url_b": "https://b"}) == frozenset(("https://a", "https://b"))
    assert labeled_pair({"name": "x"}) is None


def test_review_queue_uses_store_neutral_columns_in_a_fixed_store_order(tmp_path) -> None:
    items = [
        listing(0, "salcobrand", "Shakira", "Perfume Shakira Dance EDT 80ml", 80, "edt"),
        listing(1, "maicao", "SHAKIRA", "Dance Midnight Edt 80Ml", 80, "edt"),
        listing(2, "preunic", "Shakira", "Perfume Dance Red EDT 80 ml", 80, "edt"),
    ]
    review = [Decision(0, 1, 0.91, "review", "extra_words"), Decision(1, 2, 0.90, "review", "extra_words")]
    plan = build_plan(items, [])
    plan.review = review
    rows = list(csv.DictReader(export_review_queue(items, plan, tmp_path).open(encoding="utf-8")))
    assert list(rows[0]) == REVIEW_COLUMNS
    assert [(r["store_a"], r["store_b"]) for r in rows] == [("maicao", "salcobrand"), ("preunic", "maicao")]
    # a filled-in review file is read back as human labels
    for row in rows:
        row["label"] = "different"
    with (tmp_path / "labeled.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    assert load_overrides(tmp_path) == {frozenset((items[0].url, items[1].url)): "different",
                                        frozenset((items[1].url, items[2].url)): "different"}


def test_an_open_review_does_not_hide_the_listing() -> None:
    items = [
        listing(0, "maicao", "ANTONIO BANDERAS", "Blue Seduction Man EDT 200 mL", 200, "edt", (1, 0)),
        listing(1, "salcobrand", "Banderas", "Perfume Hombre Blue Seduction Eau de Toilette 200 ml", 200, "edt", (1, 0.01)),
    ]
    review = Decision(0, 1, 0.95, "review", "extra_words")
    plan = build_plan(items, [review])
    assert [plan.status[i][0] for i in (0, 1)] == ["new_product", "new_product"]  # both visible, apart
    assert plan.status[0][1] != plan.status[1][1]
    assert plan.review == [review]                                              # the pair waits for a human
    assert plan.stats["in_review_queue"] == 2
    # once a human labels it "same" (decide turns it into auto:human_same), it is one product
    labeled = build_plan(items, [Decision(0, 1, 0.95, "auto", "human_same")])
    assert labeled.status[0][1] == labeled.status[1][1] and labeled.status[0][0] == "matched"


def test_only_listings_without_a_volume_stay_pending() -> None:
    items = [listing(0, "maicao", "X", "Body Mist Kokone"), listing(1, "preunic", "X", "Body Mist Kokone Pink", 250)]
    plan = build_plan(items, [Decision(0, 1, 0.9, "review", "extra_words")])
    assert plan.status[0] == ("pending", None, None) and plan.status[1][0] == "new_product"


def test_human_labels_override_the_rules() -> None:
    items = [
        listing(0, "maicao", "SHAKIRA", "Fucsia EDP 50 ml", 50, "edp"),
        listing(1, "preunic", "Shakira", "Fucsia EDP 80 ml", 80, "edp"),
    ]
    assert [d.kind for d in decide(items)] == ["veto"]
    same = {frozenset((items[0].url, items[1].url)): "same"}
    assert [(d.kind, d.reason) for d in decide(items, same)] == [("auto", "human_same")]


def test_build_plan_creates_products_and_statuses() -> None:
    items = [
        listing(0, "maicao", "SHAKIRA", "Shakira Fucsia Elixir Edp 50Ml", 50, "edp", (1, 0)),
        listing(1, "preunic", "Shakira", "EDP Shakira Fucsia Elixir 50 ml", 50, "edp", (1, 0.01)),
        listing(2, "preunic", "Shakira", "EDP Shakira Fucsia Elixir 80 ml", 80, "edp", (1, 0.02)),
        listing(3, "preunic", "Natalie", "Body Mist Natalie Kokone", None, None, (0, 1)),
        # the same product listed twice by one store
        listing(4, "preunic", "Coral", "Coral Edt Belle 100Ml", 100, "edt", (0.5, 0.5)),
        listing(5, "preunic", "Coral", "Perfume Coral EDT Belle 100 ml", 100, "edt", (0.5, 0.5)),
        # equal word sets, different fragrances
        listing(6, "preunic", "Agatha Ruiz de la Prada", "Agatha Ruiz De La Prada Perfume Flor EDT 100 Ml", 100, "edt", (0.3, 1)),
        listing(7, "preunic", "Agatha Ruiz de la Prada", "De Flor en Flor Eau de Toilette 100 ml", 100, "edt", (0.3, 1)),
    ]
    plan = build_plan(items, decide(items))

    assert plan.status[0][0] == plan.status[1][0] == "matched"
    assert plan.status[0][1] == plan.status[1][1]            # same product
    assert plan.status[2][0] == "new_product"                # 80 ml is another product ...
    assert plan.products[plan.status[2][1]]["identity"] == plan.products[plan.status[1][1]]["identity"]  # ... same fragrance
    assert plan.status[3] == ("pending", None, None)         # no volume -> cannot be a product
    assert plan.status[4][1] == plan.status[5][1]            # store duplicate shares the product
    assert plan.status[6][1] != plan.status[7][1]            # Flor vs De Flor en Flor


def test_serialized_identity_keeps_what_tells_fragrances_apart() -> None:
    flor = serialize_identity(identity_key("Agatha Ruiz de la Prada", "Perfume Flor EDT 100 Ml"))
    de_flor = serialize_identity(identity_key("Agatha Ruiz de la Prada", "De Flor en Flor EDT 100 ml"))
    assert flor != de_flor
    assert serialize_identity(("lattafa", ("asad",), "male", frozenset())) == "lattafa|asad|male|"
    assert serialize_identity(("x", ("a", "b"), None, frozenset({"3", "2"}))) == "x|a b||2 3"
    # word order and store formatting do not change the key
    assert (serialize_identity(identity_key("Shakira", "EDP Shakira Fucsia Elixir 50 ml"))
            == serialize_identity(identity_key("SHAKIRA", "Shakira Elixir Fucsia Edp 50Ml")))


A, B, C = ("a", None, 50, "full_bottle"), ("b", None, 50, "full_bottle"), ("c", None, 50, "full_bottle")


def test_new_key_inherits_the_id_its_listings_had() -> None:
    # pair (m1, p1) was product P under key A; m1 is gone and p1 alone has key B
    assert inherit_product_ids({B: ["p1"]}, existing={A: "P"}, previous={"m1": "P", "p1": "P"}) == {B: "P"}


def test_a_key_already_in_the_database_is_not_inherited_over_without_more_history() -> None:
    # A is still in the plan (upsert keeps P), so B cannot take P
    plan = {A: ["m1"], B: ["p1"]}
    assert inherit_product_ids(plan, existing={A: "P"}, previous={"m1": "P", "p1": "P"}) == {}
    assert inherit_product_ids(plan, existing={A: "P"}, previous={"m1": "P", "p1": "P"},
                               history={"m1": 5, "p1": 5}) == {}


def test_a_split_product_keeps_its_id_with_the_part_with_more_history() -> None:
    # A store's "Scandal" and "So Scandal!" were one product P under key A (the
    # old identity dropped "so"); now "Scandal" keeps key A and "So Scandal!" has B.
    plan, previous = {A: ["scandal"], B: ["so_scandal"]}, {"scandal": "P", "so_scandal": "P"}
    assert inherit_product_ids(plan, {A: "P"}, previous, history={"scandal": 3, "so_scandal": 9}) == {B: "P"}
    assert inherit_product_ids(plan, {A: "P"}, previous, history={"scandal": 9, "so_scandal": 3}) == {}
    # Beauty Perfumes' The Icon (M) and (H): both parts have a new key, the votes tie
    plan, previous = {B: ["women"], C: ["men"]}, {"women": "P", "men": "P"}
    assert inherit_product_ids(plan, {A: "P"}, previous, history={"women": 2, "men": 7}) == {C: "P"}
    assert inherit_product_ids(plan, {A: "P"}, previous, history={"women": 7, "men": 2}) == {B: "P"}
    # same history: deterministic, the same answer every time
    tie = [inherit_product_ids(plan, {A: "P"}, previous, history={"women": 4, "men": 4}) for _ in range(3)]
    assert tie[0] == tie[1] == tie[2] and list(tie[0].values()) == ["P"]


def test_brand_new_listings_inherit_nothing() -> None:
    assert inherit_product_ids({B: ["new"]}, existing={A: "P"}, previous={"m1": "P"}) == {}


def test_each_old_product_is_inherited_once_by_the_majority() -> None:
    # split: P had 3 listings; 2 went to B, 1 to C -> B keeps P, C gets a new ID
    previous = {"x": "P", "y": "P", "z": "P"}
    assert inherit_product_ids({B: ["x", "y"], C: ["z"]}, existing={A: "P"}, previous=previous) == {B: "P"}
    # merge: B's listings came from P (2) and Q (1) -> B keeps P; Q is left to be deleted
    previous = {"x": "P", "y": "P", "z": "Q"}
    assert inherit_product_ids({B: ["x", "y", "z"]}, existing={A: "P", C: "Q"}, previous=previous) == {B: "P"}


def test_display_names() -> None:
    assert display_brand(["ANTONIO BANDERAS", "Antonio Banderas", "Antonio Banderas"]) == "Antonio Banderas"
    assert display_brand(["LATTAFA"]) == "Lattafa"
    assert display_name("Antonio Banderas", "Antonio Banderas The Icon EDT 50ml - Perfume Hombre") == "The Icon"
    assert display_name("Benjamin Vicuña", "Perfume Mujer She Is EDP 100 ml") == "She Is"
    assert display_name("Etienne", "ETIENNE ESSENCE EDP ROSE 100ML") == "Essence Rose"
    assert display_name("ARIANA GRANDE", "Ariana Grande Cloud EDP 30 ML (M)") == "Cloud"
    assert display_name("Lataffa", "Perfume Hombre Lattafa Asad EDP 100 Ml") == "Asad"
    assert display_name("HALLOWEEN", "Eau De Toilette con Vaporizador 30 mL") == ""
    assert canonical_name("Halloween", "", "edt", 30, "full_bottle") == "Halloween EDT 30 ml"
    assert canonical_name("Shakira", "Fucsia Elixir", "edp", 50, "full_bottle") == "Shakira Fucsia Elixir EDP 50 ml"
    assert canonical_name("Coral", "Musk", None, 100, "travel_set") == "Coral Musk 100 ml (set)"
