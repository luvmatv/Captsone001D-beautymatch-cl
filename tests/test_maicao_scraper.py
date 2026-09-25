from src.scrapers.stores.maicao.scraper import MaicaoScraper


class FakeLocator:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    @property
    def first(self) -> "FakeLocator":
        return self

    def count(self) -> int:
        return 1 if self.value is not None else 0

    def all_text_contents(self) -> list[str]:
        return ["Antonio Banderas"]

    def text_content(self) -> str | None:
        return self.value

    def get_attribute(self, attribute: str) -> str | None:
        return self.value if attribute == "href" else None


class FakeLink:
    def __init__(self, tile_text: str = "ANTONIO BANDERAS\nBlue Seduction Man EDT 200 mL\nAgregar") -> None:
        self.tile_text = tile_text

    def evaluate(self, expression: str) -> str:
        return self.tile_text

    def text_content(self) -> str:
        return "Blue Seduction Man EDT 200 mL"

    def get_attribute(self, attribute: str) -> str | None:
        return "/blue-seduction-man-edt-200-ml/CLMC_272822.html"

    def locator(self, selectors: str) -> FakeLocator:
        return FakeCard() if selectors == "xpath=.." else FakeLocator(None)


class FakeCard:
    def locator(self, selectors: str) -> FakeLocator:
        return FakeLocator("Antonio Banderas" if "aria-label" in selectors else None)

    def inner_text(self) -> str:
        return "Antonio Banderas Blue Seduction Man EDT 200 mL $35.999 $26.999"

    def evaluate(self, expression: str) -> list[dict]:
        return [
            {"text": "$35.999", "struck": True},
            {"text": "$26.999", "struck": False},
        ]


def test_product_from_link_extracts_maicao_fields() -> None:
    product = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")._product_from_link(
        FakeLink(), "https://www.maicao.cl/perfumes-y-fragancias/"
    )

    assert product.name == "Blue Seduction Man EDT 200 mL"
    assert product.brand == "Antonio Banderas"
    assert product.current_price == "$26.999"
    assert product.previous_price == "$35.999"
    assert product.volume == "200 mL"
    assert product.concentration == "EDT"
    assert product.availability == "available"


def test_product_from_link_reads_stock_badge_from_whole_tile() -> None:
    link = FakeLink("Sin stock online\nANTONIO BANDERAS\nBlue Seduction Man EDT 200 mL\nVer disponibilidad")

    product = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")._product_from_link(
        link, "https://www.maicao.cl/perfumes-y-fragancias/"
    )

    assert product.availability == "Sin stock online"
