from src.scrapers.stores.preunic.scraper import PreunicScraper


class FakeLocator:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    @property
    def first(self) -> "FakeLocator":
        return self

    def count(self) -> int:
        return 1 if self.value is not None else 0

    def text_content(self) -> str | None:
        return self.value

    def get_attribute(self, attribute: str) -> str | None:
        return self.value if attribute == "href" else None

    def all_text_contents(self) -> list[str]:
        return ["Marca Test", "Eau de parfum Test"]


class FakeCard:
    def inner_text(self) -> str:
        return "$24.990\n$19.990\n$19.990 x 100 ML"

    def evaluate(self, expression: str) -> list[dict]:
        return [
            {"text": "$24.990", "struck": True},
            {"text": "$19.990", "struck": False},
        ]

    def locator(self, selectors: str) -> FakeLocator:
        if selectors == "p":
            return FakeLocator()
        values = {
            "a[href]": "/products/test",
        }
        return FakeLocator(values.get(selectors))


def test_product_from_card_extracts_comparison_fields() -> None:
    product = PreunicScraper("https://example.test/perfumes")._product_from_card(
        FakeCard(), "https://example.test/perfumes"
    )

    assert product.name == "Eau de parfum Test"
    assert product.brand == "Marca Test"
    assert product.current_price == "$19.990"
    assert product.previous_price == "$24.990"


def test_volume_from_technical_sheet() -> None:
    read = PreunicScraper._volume_from_technical_sheet

    assert read("Ficha técnica\nMarca:\n\nEminence\n\nFormato:\n\n100ml\n\nClasificación:\n\nHombre\n\n") == "100ml"
    assert read("Ficha técnica\nMarca:\n\nNATALIE\n\nFormato:\n\n250 ml\n\nClasificación:\n\nMujer\n\n") == "250 ml"
    assert read("Ficha técnica\nMarca:\n\nPlaisance\n\nFormato:\n\n1 uni\n\nClasificación:\n\nMujer\n\n") is None
    assert read("Ficha técnica\nPresentación:\n\n1 Unidad\n\nTipo:\n\nPerfume\n\n") is None
    assert read(None) is None


def test_extract_concentration_handles_spanish_and_misspelled_names() -> None:
    extract = PreunicScraper._extract_concentration

    assert extract("Agua de parfum Acqua") == "EDP"
    assert extract("Piero Red, Eau de Toillette de Hombre") == "EDT"
    assert extract("Agua de colonia fresca") == "EDC"
    assert extract("Perfume Etienne Essence Aura 100 Ml") is None
