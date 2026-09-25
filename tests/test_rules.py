import pytest

from src.matching.rules import GenderIndex, different_names, edition_numbers, gender, variant_words, veto

CATALOG = [
    ("preunic", "Antonio Banderas", "Antonio Banderas The Icon EDT 100ml - Perfume Hombre", 100, "edt"),
    ("preunic", "Antonio Banderas", "Fragancia The Icon Femenino EDP 50 ML", 50, "edp"),
    ("maicao", "ANTONIO BANDERAS", "The Icon Elixir EDP 50ML", 50, "edp"),
    ("maicao", "ANTONIO BANDERAS", "The Icon Elixir Women Edp 50Ml", 50, "edp"),
    ("preunic", "Quorum", "Estuche Perfume Hombre Quorum 100 Ml + Desodorante 150 Ml", 100, "edt"),
    ("preunic", "Quorum", "QUORUM Eau de Toilette de 100ml", 100, "edt"),
]
GENDERS = GenderIndex(CATALOG)


def test_gender_words() -> None:
    assert gender("Antonio Banderas", "Banderas Perfumes Mujer The Icon Supreme EDP 50ml") == "female"
    assert gender("Antonio Banderas", "Eau de Toilette Blue seduction For Men 100 mL") == "male"
    assert gender("Antonio Banderas", "Queen of Seduction Summerland Eau de Toilette 80 ml") == "female"
    assert gender("Quorum", "QUORUM Eau de Toilette de 100ml") is None


@pytest.mark.parametrize(
    ("brand", "name", "numbers"),
    [
        ("Ariana Grande", "Body Mist Ariana Grande Thank U Next 2.0 236 Ml", {"2.0"}),
        ("ARIANA GRANDE", "ARIANA GR.THAN2.0 SP.236M", {"2.0"}),
        ("ARIANA GRANDE", "ARIANA GR.SWEE.LIK.EDP.30", set()),
        ("Victorio & Lucchino", "Fragancia Mujer Victorio & Lucchino Aguas Florales N°3 Edt 150 Ml", {"3"}),
        ("Victorio & Lucchino", "Fragancia Mujer Victorio & Lucchino Aguas Frutales Nº18 Vitamina Citrica Edt 150 Ml", {"18"}),
        ("Afnan", "Afnan 9Am Dive Unisex 100 ml", {"9am"}),
        ("Billie Eilish", "Perfume Billie Eilish Vol. 1 EDP 30 ml", {"1"}),
        ("Shakira", "Skr Perfume Dance Red Midnight 2021 Edt 50Ml", set()),
        ("Beauty Secret", "Estuche Beauty Secret Body Mist 150 + Body Mist 15 + Body Lotion 120", set()),
        ("Flaño", "Pack Flaño Loción FM 120cc+Desod Spray", set()),
    ],
)
def test_edition_numbers(brand, name, numbers) -> None:
    assert edition_numbers(brand, name) == numbers


def test_different_edition_numbers_are_variants() -> None:
    assert veto(("Ariana Grande", "Body Mist ARIANA GRANDE THANK U NEXT 236 Ml"),
                ("ARIANA GRANDE", "ARIANA GR.THAN2.0 SP.236M"), GENDERS) == "variant"
    assert veto(("Victorio & Lucchino", "Aguas Florales N°3 Edt 150 Ml"),
                ("VICTORIO & LUCCHINO", "Aguas Florales N°4 Edt 150 Ml"), GENDERS) == "variant"


def test_litre_unit_is_not_a_name() -> None:
    # "1Lt" must not count as a name word; what is left is a one-sided extra (ambiguous)
    assert not different_names(
        ("Bellekiss", "Bellekiss Colonia 1Lt Fresh"),
        ("BELLEKISS", "Colonia Fresca Floral Familiar 1000 mL"),
    )


def test_variant_words_normalize_de_luxe() -> None:
    assert variant_words("Millionaire", "Eau de toilette Gold de Luxe") == {"gold", "deluxe"}


@pytest.mark.parametrize(
    ("a", "b", "reason"),
    [
        (("Antonio Banderas", "Perfume Hombre Banderas Icon Man Supreme 50 ML"),
         ("ANTONIO BANDERAS", "Banderas Perfumes Mujer The Icon Supreme EDP 50ml"), "gender"),
        (("Antonio Banderas", "Banderas Hombre King of Seduction Summerland Eau de Toilette 100 ml"),
         ("ANTONIO BANDERAS", "Queen of Seduction Summerland Eau de Toilette 80 ml"), "gender"),
        (("Antonio Banderas", "Perfume The Icon Elixir Antonio Banderas Edp 50 Ml"),
         ("ANTONIO BANDERAS", "The Icon Elixir Women Edp 50Ml"), "gender"),
        (("Antonio Banderas", "Perfume The Icon Elixir Antonio Banderas Edp 50 Ml"),
         ("ANTONIO BANDERAS", "Perfume The Icon New Eau De Parfum 50 mL"), "variant"),
        (("Antonio Banderas", "Eau de Toilette KING OF SEDUCTION"),
         ("ANTONIO BANDERAS", "King Seduction Absolute Eau de Toilette de 50 mL"), "variant"),
        # one side unmarked, catalog carries both genders of The Icon
        (("Antonio Banderas", "Fragancia The Icon Femenino EDP 50 ML"),
         ("ANTONIO BANDERAS", "The Icon EDT 200ML"), "gender"),
        (("Eminence", "Set Eminence Sport Edp 100Ml + Desodorante Spray 160Ml"),
         ("EMINENCE", "Perfume Sport EDP 100 ml"), "presentation"),
        (("Antonio Banderas", "Estuche Antonio Banderas Her Secret Perfume 50ml Spray"),
         ("ANTONIO BANDERAS", "Her Secret Eau de Toilette 50 mL"), "presentation"),
        (("Plaisance", "Perfume Plaisance Hotphoria Power EDP 80 Ml"),
         ("PLAISANCE", "Perfume Hotphoria Peace EDP 80ml"), "name"),
        (("Jean Les Pins", "Fragancia Jean Les Pins Agua de Gardenia EDT 100 ml"),
         ("JEAN LES PINS", "Fragancia Agua de Magnolia EDT 100 ml"), "name"),
        (("Etienne", "Perfume Etienne Essence Rose 100 Ml"),
         ("ETIENNE", "Perfume Rouge 100ml"), "name"),
        (("Benjamin Vicuña", "Perfume Hombre He Is EDP 100 ml"),
         ("BENJAMIN VICUÑA", "Perfume Mujer She Is EDP 100 ml"), "gender"),
        # "Mignight" is a misspelled flanker word
        (("Shakira", "Estuche Perfume Mujer Shakira Dance Mignight Edt 50Ml + Loción Corporal 75Ml"),
         ("SHAKIRA", "Dance Eau De Toilette Natural Spray 50 mL + Body Lotion 75 mL"), "variant"),
    ],
)
def test_veto_blocks_gender_versions_and_flankers(a, b, reason) -> None:
    assert veto(a, b, GENDERS) == reason


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (("Antonio Banderas", "Perfume The Icon Elixir Antonio Banderas Edp 50 Ml"),
         ("ANTONIO BANDERAS", "The Icon Elixir EDP 50ML")),
        (("Antonio Banderas", "Perfume Hombre Banderas Icon Man Supreme 50 ML"),
         ("ANTONIO BANDERAS", "Banderas Perfume Hombre The Icon Supreme EDP 50ml")),
        # gender only on one side, and the catalog has no female Quorum
        (("Quorum", "Perfume Hombre Quorum EDT 100 ml"),
         ("QUORUM", "QUORUM Eau de Toilette de 100ml")),
        (("Sabrina Carpenter", "EDP Sabrina Carpenter Caramel 30ML"),
         ("SABRINA CARPENTER", "Sabrina Carpenter Caramel Dream EDP 75 ML")),
        (("Eminence", "Set Eminence Sport Edp 100Ml + Desodorante Spray 160Ml"),
         ("EMINENCE", "Set Sport Eau de Parfum 100 mL + Desodorante Spray 160 mL")),
        # spelling variant (jeans/jean) and a word joined differently
        (("Jean Les Pins", "Fragancia Mujer Jeans Les Pins Agua de Jazmín EDT 100 ml"),
         ("JEAN LES PINS", "Fragancia Agua de Jazmin EDT 100ml")),
        (("Sabrina Carpenter", "EDP Sabrina Carpenter Sweettooth 30ML"),
         ("SABRINA CARPENTER", "Sabrina Carpenter Sweet Tooth EDP 30 ML")),
        (("Sabrina Carpenter", "Body Mist Sabrina Carpenter Sweettooth 236 ml"),
         ("SABRINA CARPENTER", "Sabrina Carpenter Sweet Tooth 236 ML")),
        (("Piero Butti", "Piero Butti Eau de Toilette il Capo 100 ml"),
         ("PIERO BUTTI", "Perfume de Hombre ll Capo 100 mL")),
        (("Antonio Banderas", "Estuche Banderas Her Golden Secret 50ml + Body Lotion 75ml"),
         ("ANTONIO BANDERAS", "Her Golden Secret Eau De Toilette 50 mL+ Loción Hidratante Cuerpo 75 mL")),
        (("Shakira", "Estuche Perfume Mujer Shakira Dance Edt 50Ml + Loción Corporal 75Ml"),
         ("SHAKIRA", "Dance Eau De Toilette Natural Spray 50 mL + Body Lotion 75 mL")),
    ],
)
def test_veto_allows_same_product_written_differently(a, b) -> None:
    assert veto(a, b, GENDERS) is None
