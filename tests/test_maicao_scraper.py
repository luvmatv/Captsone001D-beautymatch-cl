import json
from pathlib import Path

import pytest

from src.loader.conversions import to_volume_ml
from src.scrapers.stores.maicao.scraper import (
    PRODUCT_LINK,
    MaicaoScraper,
    ProductRecord,
    search_total,
    unpriced_hits,
    volume_from_product_page,
)

# Product pages, abbreviated. The "Contenido:" lines are exactly as read on 2026-09-30
# (CLMC_575825, CLMC_577014); the set page (CLMC_578879) has no such line.
FRUITY_BOOM_PAGE = "Body Splash Fruity Boom\n$4.990\nDescripción\nContenido: 250 Ml\nModo de uso: aplicar sobre la piel"
HOTPHORIA_POWER_PAGE = "Perfume Hotphoria Power EDP\n$13.990\nDescripción\nContenido: 80 ml.\nGénero: Femenino"
HELLO_KITTY_SET_PAGE = "Set Perfume Hello Kitty Edt + Espejo\n$9.990\nDescripción\nIncluye: perfume 100 ml + espejo"


@pytest.mark.parametrize(("text", "volume_ml"), [
    (FRUITY_BOOM_PAGE, 250),
    (HOTPHORIA_POWER_PAGE, 80),
    (HELLO_KITTY_SET_PAGE, None),          # sets have no "Contenido:" line: no volume, not a guess
    ("Contenido: 1 unidad", None),         # a "Contenido:" that is not a size
    (None, None),
])
def test_volume_from_product_page(text, volume_ml) -> None:
    assert to_volume_ml(volume_from_product_page(text)) == volume_ml


class FakeProductPage:
    def __init__(self, pages: dict[str, str], failing: set[str] = frozenset()) -> None:
        self.pages, self.failing, self.visited, self.url = pages, failing, [], ""

    def goto(self, url, **kwargs):
        self.visited.append(url)
        if url in self.failing:
            raise RuntimeError("net::ERR_TIMED_OUT")
        self.url = url

    def wait_for_function(self, expression, timeout=None): pass
    def wait_for_timeout(self, ms): pass
    def inner_text(self, selector): return self.pages[self.url]


def record(name, url, volume=None):
    return ProductRecord(name=name, brand=None, current_price="$1.000", previous_price=None, volume=volume,
                         concentration=None, url=url, image_url=None, availability="available",
                         volume_source="listing_name" if volume else None)


def test_product_pages_fill_only_missing_volumes() -> None:
    fruity = record("Body Splash Fruity Boom", "https://www.maicao.cl/body-splash-fruity-boom/CLMC_575825.html")
    power = record("Perfume Hotphoria Power EDP", "https://www.maicao.cl/perfume-hotphoria-power-edp/CLMC_577014.html")
    kitty = record("Set Perfume Hello Kitty Edt + Espejo", "https://www.maicao.cl/set-hello-kitty/CLMC_578879.html")
    broken = record("Perfume Roto", "https://www.maicao.cl/roto/CLMC_1.html")
    named = record("Belle Edt 100ml", "https://www.maicao.cl/belle-edt-100ml/CLMC_535402.html", volume="100ml")
    page = FakeProductPage({fruity.url: FRUITY_BOOM_PAGE, power.url: HOTPHORIA_POWER_PAGE, kitty.url: HELLO_KITTY_SET_PAGE},
                           failing={broken.url})
    stats = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")._volumes_from_product_pages(
        page, [fruity, power, kitty, broken, named], {"progress": {}}, None)

    assert named.url not in page.visited and len(page.visited) == 4    # only products without a volume
    assert (to_volume_ml(fruity.volume), fruity.volume_source) == (250, "product_page")
    assert (to_volume_ml(power.volume), power.volume_source) == (80, "product_page")
    assert kitty.volume is None and broken.volume is None
    assert stats == {"products_total": 5, "volume_before": 1, "attempted": 4, "volume_enriched": 2,
                     "volume_not_available": 1, "failed": 1, "volume_after": 3}


# Real response of the last listing page (offset 300) on 2026-09-30, trimmed:
# 5 CLMC_ products and the 2 with numeric ids and no price.
OFFSET_300 = json.loads((Path(__file__).parent / "fixtures/maicao/product_search_offset300.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("href", "product_id"), [
    ("/belle-edt-100ml/CLMC_535402.html?cgid=perfumes-y-fragancias", "CLMC_535402"),
    ("/perfume-edp-gold-elixir-100ml/580587.html?cgid=perfumes-y-fragancias", "580587"),
    ("/perfume-edp-absolutely-blue-100ml/580588.html?cgid=perfumes-y-fragancias", "580588"),
    ("https://www.maicao.cl/servicio-al-cliente/cobertura.html", None),      # footer links are not products
    ("https://www.maicao.cl/club/beneficios.html", None),
])
def test_product_links_include_numeric_ids(href, product_id) -> None:
    match = PRODUCT_LINK.search(href)
    assert (match.group(1) if match else None) == product_id


def test_unpriced_hits_are_the_two_products_not_on_sale() -> None:
    assert OFFSET_300["total"] == 307 and len(OFFSET_300["hits"]) == 7
    assert unpriced_hits(OFFSET_300) == {"580587", "580588"}   # Gold Elixir and Absolutely Blue
    assert unpriced_hits({"hits": []}) == set() and unpriced_hits(None) == set()


class FakeListingPage:
    """Category pages by offset; each product appears as two links (image and name), as on Maicao."""

    def __init__(self, products_by_offset: dict[int, list[str]]) -> None:
        self.products_by_offset, self.url, self.visited = products_by_offset, "", []

    def goto(self, url, **kwargs):
        self.url = url
        self.visited.append(int(url.split("offset=")[1]) if "offset=" in url else 0)

    def wait_for_timeout(self, ms): pass
    def evaluate(self, script): pass

    def locator(self, selector):
        urls = self.products_by_offset.get(self.visited[-1], [])
        return FakeLinks([url for url in urls for _ in range(2)])


class FakeLinks:
    def __init__(self, urls): self.urls = urls
    def count(self): return len(self.urls)
    def nth(self, index): return self.urls[index]


def test_the_last_page_is_short_by_products_not_by_links(monkeypatch) -> None:
    # 26 pages: 25 full pages of 12 and a last one with 7 products (14 links,
    # more than the page size of 12): it must still end as short_page.
    pages = {offset: [f"https://www.maicao.cl/p/CLMC_{offset + i}.html" for i in range(12)] for offset in range(0, 300, 12)}
    pages[300] = [f"https://www.maicao.cl/p/CLMC_{300 + i}.html" for i in range(5)] + [
        "https://www.maicao.cl/perfume-edp-gold-elixir-100ml/580587.html",
        "https://www.maicao.cl/perfume-edp-absolutely-blue-100ml/580588.html"]
    scraper = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")
    monkeypatch.setattr(scraper, "_product_from_link", lambda url, page_url: ProductRecord(
        name="x", brand=None, current_price="$1.000", previous_price=None, volume=None, concentration=None,
        url=url, image_url=None, availability="available"))
    monkeypatch.setattr(scraper, "_last_offset", lambda page: 300)
    page = FakeListingPage(pages)
    products, pagination = scraper._scrape_pages(page, {"progress": {}}, None)
    assert len(products) == 307
    assert pagination["stop_reason"] == "short_page" and pagination["catalog_exhausted"]
    assert page.visited[-1] == 300   # it did not go on to an empty page

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
