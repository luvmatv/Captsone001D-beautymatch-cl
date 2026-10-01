import pytest

from src.scrapers.concentration import extract_concentration


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Colonia Hombre Black", "EDC"),
        ("COLONIA INGLESA CELL SKIN BLUE 1000 ml", "EDC"),
        ("Baby Colonia Hipoalergénica 190 mL", "EDC"),
        ("Colónia Fresca 200 ml", "EDC"),
        ("Fragancia Jean Les Pins Silvestre Agua de Colonia JLP 255 ml", "EDC"),
        ("King Of Seduction Colonia EDT de 200 mL", "EDT"),
        ("Coloniales Body Mist 200 ml", None),
    ],
)
def test_colonia_maps_to_edc_unless_a_specific_concentration_is_named(name, expected) -> None:
    assert extract_concentration(name) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # store typos of "Eau de Parfum" (real names)
        ("Etienne Eau de Perfum Aura Violette 100 ml", "EDP"),
        ("Millionaire Eau de Perfum Gold Elixir 100 ml", "EDP"),
        ("Eminence Eau The Parfum Absolutely Blue 100 ml", "EDP"),      # was PARFUM
        ("Millionaire eau the parfum Gold Deluxe 100 ml", "EDP"),
        # "The Parfum" without "eau" is a fragrance name; its concentration is stated apart
        ("Perfume Hombre The Icon The Parfum Eau de Parfum 50 ml", "EDP"),
        ("Halloween Parfum 100 ml", "PARFUM"),                          # a real parfum stays parfum
    ],
)
def test_eau_de_parfum_typos_are_edp(name, expected) -> None:
    assert extract_concentration(name) == expected
