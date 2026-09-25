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
