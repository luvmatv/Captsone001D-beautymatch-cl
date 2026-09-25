from src.matching.embeddings import listing_text, to_pgvector


def test_listing_text_prefixes_and_lowercases_brand_and_name() -> None:
    assert (
        listing_text("ANTONIO BANDERAS", "Blue Seduction Man EDT 200 mL")
        == "query: antonio banderas blue seduction man edt 200 ml"
    )


def test_listing_text_does_not_repeat_brand_already_in_name() -> None:
    assert (
        listing_text("Etienne", "Perfume Mujer Aura Violet  Etienne 100 Ml")
        == "query: perfume mujer aura violet etienne 100 ml"
    )


def test_listing_text_expands_abbreviations_before_checking_brand() -> None:
    assert (
        listing_text("ARIANA GRANDE", "ARIANA GR.MOD VAI.SP236ML")
        == "query: ariana grande mod vanilla spray 236 ml"
    )


def test_listing_text_without_brand() -> None:
    assert listing_text(None, "Colonia Pino 90 mL") == "query: colonia pino 90 ml"


def test_to_pgvector() -> None:
    assert to_pgvector([0.5, -0.25]) == "[0.5000000,-0.2500000]"
