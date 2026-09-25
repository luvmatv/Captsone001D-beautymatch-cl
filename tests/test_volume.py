import pytest

from src.scrapers.volume import extract_volume


@pytest.mark.parametrize(
    ("name", "volume"),
    [
        ("Paris Hilton Can Can Woman Edp X30Ml", "30Ml"),
        ("P.hilton Body Mist X236ml Can Can", "236ml"),
        ("Perfume Mujer Antonio Banderas Blue Seduction Summer Essence EDT100 Ml", "100 Ml"),
        ("ARIANA GR.MOD VAI.SP236ML", "236ML"),
        ("Bellekiss Colonia 1Lt Fresh", "1Lt"),
        ("Colonia Inglesa Clasica 1 Litro Cell Skin", "1 Litro"),
        ("Pack Flaño Loción FM 120cc+Desod Spray", "120cc"),
        ("Blue Seduction Man EDT 200 mL", "200 mL"),
        ("Etienne Noir 100ml NDP", "100ml"),
        ("Perfume Blue Seduction", None),
        ("Thank U Next 2.0", None),
    ],
)
def test_extract_volume(name, volume) -> None:
    assert extract_volume(name) == volume
