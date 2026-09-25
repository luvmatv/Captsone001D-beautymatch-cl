from decimal import Decimal

import pytest

from src.loader.conversions import (
    listing_from_product,
    normalize_url,
    to_concentration,
    to_price,
    to_volume_ml,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("EDP", "edp"), ("EDT", "edt"), ("EDC", "cologne"), ("PARFUM", "parfum"), (None, None)],
)
def test_to_concentration(value, expected) -> None:
    assert to_concentration(value) == expected


def test_to_concentration_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        to_concentration("EXTRAIT")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("$19.990", Decimal(19990)), ("$999", Decimal(999)), ("$1.234.567", Decimal(1234567)),
     ("$ 9.999", Decimal(9999)), (None, None), ("", None)],
)
def test_to_price(value, expected) -> None:
    assert to_price(value) == expected


@pytest.mark.parametrize("value", ["19.990", "$19,99", "$19.99", "precio actual $19.990"])
def test_to_price_rejects_other_formats(value) -> None:
    with pytest.raises(ValueError):
        to_price(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("200 mL", 200), ("100ml", 100), ("50 Ml", 50), ("30Ml", 30), ("1 L", 1000),
     ("1,5 L", 1500), ("1.000 ml", 1000), ("7,5 ml", 8), ("3 un", None), (None, None)],
)
def test_to_volume_ml(value, expected) -> None:
    assert to_volume_ml(value) == expected


def test_normalize_url_drops_query_and_fragment() -> None:
    assert (
        normalize_url("https://www.maicao.cl/a/CLMC_272822.html?cgid=perfumes-y-fragancias#top")
        == "https://www.maicao.cl/a/CLMC_272822.html"
    )


def test_listing_from_maicao_product() -> None:
    listing = listing_from_product(
        "maicao",
        {
            "name": " Blue Seduction Man EDT 200 mL ",
            "brand": "ANTONIO BANDERAS",
            "current_price": "$26.999",
            "previous_price": "$35.999",
            "volume": "200 mL",
            "concentration": "EDT",
            "url": "https://www.maicao.cl/blue-seduction-man-edt-200-ml/CLMC_272822.html?cgid=x",
            "availability": "Sin stock online",
        },
    )

    assert listing.listing_url == "https://www.maicao.cl/blue-seduction-man-edt-200-ml/CLMC_272822.html"
    assert listing.store_sku == "CLMC_272822"
    assert listing.raw_name == "Blue Seduction Man EDT 200 mL"
    assert listing.parsed_concentration == "edt"
    assert listing.parsed_volume_ml == 200
    assert listing.price == Decimal(26999)
    assert listing.list_price == Decimal(35999)
    assert listing.is_available is False


def test_listing_falls_back_to_concentration_in_name() -> None:
    listing = listing_from_product(
        "preunic",
        {
            "name": "Colonia Hombre Black",
            "brand": "Brut",
            "current_price": "$3.999",
            "concentration": None,
            "url": "https://preunic.cl/products/colonia-hombre-black",
        },
    )

    assert listing.parsed_concentration == "cologne"


def test_listing_from_preunic_product_without_optional_fields() -> None:
    listing = listing_from_product(
        "preunic",
        {
            "name": "Perfume Etienne Essence Aura 100 Ml",
            "brand": "Etienne",
            "current_price": "$9.999",
            "previous_price": None,
            "volume": None,
            "concentration": None,
            "url": "https://preunic.cl/products/perfume-etienne-essence-aura-100-ml",
            "availability": None,
        },
    )

    assert listing.store_sku is None
    assert listing.parsed_concentration is None
    assert listing.parsed_volume_ml is None
    assert listing.list_price is None
    assert listing.is_available is True
