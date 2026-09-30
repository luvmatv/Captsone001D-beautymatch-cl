import json

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.scrapers.stores.preunic import scraper as preunic
from src.scrapers.stores.preunic.scraper import NoProductCards, PreunicScraper, parse_site_total


class FakeListingPage:
    """Only what scrape() touches before the cards are read."""

    def __init__(self, cards_appear: bool, controls_appear: bool = True) -> None:
        self.cards_appear, self.controls_appear = cards_appear, controls_appear
        self.url = "https://preunic.cl/t/perfumes-y-fragancias"
        self.waited_for = []

    def set_default_timeout(self, ms): pass
    def set_default_navigation_timeout(self, ms): pass
    def goto(self, url, **kwargs): pass

    def wait_for_timeout(self, ms):
        raise AssertionError("no fixed waits: wait for the cards themselves")

    def wait_for_selector(self, selector, state=None, timeout=None):
        self.waited_for.append((selector, timeout))
        if not self.cards_appear:
            raise PlaywrightTimeoutError(f"waiting for {selector}")

    def wait_for_function(self, expression, arg=None, timeout=None):
        if not self.controls_appear:
            raise PlaywrightTimeoutError("controls")


class FakePlaywright:
    def __init__(self, page) -> None:
        self.page, self.chromium = page, self

    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def launch(self, headless=True): return self
    def new_page(self): return self.page
    def close(self): pass


def test_waits_for_the_cards_instead_of_a_fixed_delay() -> None:
    page = FakeListingPage(cards_appear=True)
    PreunicScraper("https://preunic.cl/t/perfumes-y-fragancias")._wait_for_cards(page)
    assert page.waited_for == [(PreunicScraper.product_selector, preunic.CARDS_TIMEOUT_MS)]
    assert preunic.CARDS_TIMEOUT_MS == 30000


def test_missing_controls_only_warn(caplog) -> None:
    PreunicScraper("x")._wait_for_cards(FakeListingPage(cards_appear=True, controls_appear=False))
    assert "neither the load-more button nor the total appeared" in caplog.text


def test_no_cards_is_an_explicit_failure_not_an_empty_catalog(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(preunic, "sync_playwright", lambda: FakePlaywright(FakeListingPage(cards_appear=False)))
    output = tmp_path / "preunic.json"
    with pytest.raises(NoProductCards, match="no product card"):
        PreunicScraper("https://preunic.cl/t/perfumes-y-fragancias").scrape(output_path=output)
    snapshot = json.loads(output.read_text(encoding="utf-8"))
    assert snapshot["progress"]["step"] == "listing:wait_cards"  # never "done"
    assert snapshot["products"] == [] and snapshot["pagination"] is None
    assert snapshot["failures"][0]["step"] == "listing:wait_cards"
    assert "NoProductCards" in snapshot["failures"][0]["error"]


@pytest.mark.parametrize(("texts", "expected"), [
    (["497 productos"], 497),
    (["497 producto s"], 497),        # how the page splits it into text nodes
    (["497\nproducto\ns"], 497),
    (["1 producto"], 1),
    (["1.234 productos"], 1234),
    (["Ordenar y Filtrar", "24 productos"], 24),
    (["Envío gratis en productos seleccionados", "Hasta 50% en 200 productos"], None),
    ([], None),
])
def test_parse_site_total(texts, expected) -> None:
    assert parse_site_total(texts) == expected


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
