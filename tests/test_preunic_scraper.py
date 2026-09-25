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
        return "$19.990\n$24.990"

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
