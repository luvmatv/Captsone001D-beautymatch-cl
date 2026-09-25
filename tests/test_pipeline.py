import numpy as np
import pytest

from src.matching.pipeline import (
    Decision,
    Listing,
    build_plan,
    canonical_name,
    classify,
    decide,
    display_brand,
    display_name,
    one_to_one,
)
from src.matching.rules import GenderIndex


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


def test_one_to_one_keeps_the_most_similar_pair_for_each_listing() -> None:
    items = [listing(0, "preunic", "X", "a"), listing(1, "maicao", "X", "a"), listing(2, "maicao", "X", "a")]
    decisions = [Decision(0, 1, 0.95, "auto", "same_name"), Decision(0, 2, 0.99, "auto", "same_name")]
    assert one_to_one(items, decisions) == [decisions[1]]


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
