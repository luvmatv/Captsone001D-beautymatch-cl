import pytest

from src.matching.rules import GenderIndex, gender, variant_words, veto

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
        (("Quorum", "Estuche Perfume Hombre Quorum 100 Ml + Desodorante 150 Ml"),
         ("QUORUM", "QUORUM Eau de Toilette de 100ml")),
        (("Sabrina Carpenter", "EDP Sabrina Carpenter Caramel 30ML"),
         ("SABRINA CARPENTER", "Sabrina Carpenter Caramel Dream EDP 75 ML")),
    ],
)
def test_veto_allows_same_product_written_differently(a, b) -> None:
    assert veto(a, b, GENDERS) is None
