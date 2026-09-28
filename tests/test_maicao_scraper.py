import pytest

from src.scrapers.stores.maicao.scraper import MaicaoScraper, search_total

SEARCH = ("https://www.maicao.cl/mobify/proxy/api/search/shopper-search/v1/organizations/f_ecom_bdpm_prd/"
          "product-search?siteId=MaicaoChile&refine=cgid%3Dperfumes-y-fragancias&sort=best-matches&limit=12&offset=24")


@pytest.mark.parametrize(("url", "data", "expected"), [
    (SEARCH, {"total": 305, "offset": 24, "hits": []}, 305),
    (SEARCH, {"total": 0, "hits": []}, 0),
    (SEARCH.replace("perfumes-y-fragancias", "maquillaje"), {"total": 3006}, None),        # another category
    (SEARCH + "&refine=brand%3DSHAKIRA", {"total": 28}, None),                          # a filtered search
    (SEARCH.replace("product-search", "product-search-suggestions"), {"total": 5}, None),  # not the listing search
    (SEARCH, {"hits": []}, None),                                                        # the response changed
    (SEARCH, {"total": "305"}, None),
    (SEARCH, {"total": True}, None),
    (SEARCH, ["not", "a", "dict"], None),
])
def test_search_total(url, data, expected) -> None:
    assert search_total(url, data, "perfumes-y-fragancias") == expected


def test_category_id_comes_from_the_category_url() -> None:
    assert MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias").category_id == "perfumes-y-fragancias"


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
