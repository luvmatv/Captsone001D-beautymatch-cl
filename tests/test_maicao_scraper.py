import json
from dataclasses import asdict
from pathlib import Path

import pytest

from src.loader.conversions import listing_from_product, to_volume_ml
from src.scrapers.stores.maicao.scraper import (
    PRODUCT_LINK,
    MaicaoScraper,
    ProductRecord,
    empty_page_report,
    hit_images,
    search_total,
    unpriced_hits,
    usable_image,
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
    asad = record("Asad DESO.SP200M", "https://www.maicao.cl/asad-desosp200m/CLMC_589474.html")
    page = FakeProductPage({fruity.url: FRUITY_BOOM_PAGE, power.url: HOTPHORIA_POWER_PAGE, kitty.url: HELLO_KITTY_SET_PAGE},
                           failing={broken.url})
    stats = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")._volumes_from_product_pages(
        page, [fruity, power, kitty, broken, named, asad], {"progress": {}}, None)

    assert page.visited == [fruity.url, power.url, kitty.url, broken.url]    # only products without a volume
    assert (to_volume_ml(fruity.volume), fruity.volume_source) == (250, "product_page")
    assert (to_volume_ml(power.volume), power.volume_source) == (80, "product_page")
    assert kitty.volume is None and broken.volume is None
    assert stats == {"products_total": 6, "volume_before": 1, "volume_from_abbreviations": 1, "attempted": 4,
                     "volume_enriched": 2, "volume_not_available": 1, "failed": 1, "volume_after": 4}


def test_abbreviated_name_is_not_visited_and_the_loader_reads_its_volume() -> None:
    # "SP200M" is not a volume until the abbreviations are expanded (spray 200 ml)
    asad = record("Asad DESO.SP200M", "https://www.maicao.cl/asad-desosp200m/CLMC_589474.html")
    assert asad.volume is None
    page = FakeProductPage({})
    stats = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")._volumes_from_product_pages(
        page, [asad], {"progress": {}}, None)

    assert page.visited == [] and stats["attempted"] == 0 and stats["volume_from_abbreviations"] == 1
    assert asad.volume is None and asad.volume_source is None   # the scraper keeps what the listing said
    assert listing_from_product("maicao", asdict(asad)).parsed_volume_ml == 200


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
    assert pagination["empty_page"] is None


class Response:
    status = 200


class EmptyListingPage(FakeListingPage):
    """The first page as on 2026-10-18: no product links, although the search API had answered."""

    def __init__(self):
        super().__init__({})

    def goto(self, url, **kwargs):
        super().goto(url)
        return Response()

    def evaluate(self, script):
        if "html_links" in script:
            return {"links": 41, "html_links": 3, "text": "Perfumes y Fragancias Ordenar por 339 resultados"}

    def title(self): return "Perfumes y Fragancias | Maicao"
    def content(self): return "<html><body>Perfumes y Fragancias</body></html>"

    def screenshot(self, path, full_page):
        Path(path).write_bytes(b"\x89PNG")


def test_a_page_without_product_links_keeps_what_it_showed(tmp_path, caplog) -> None:
    scraper = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")
    scraper.search_responses = 1
    output = tmp_path / "maicao_20261019T000451Z.json"
    caplog.set_level("WARNING")
    products, pagination = scraper._scrape_pages(EmptyListingPage(), {"progress": {}}, output)

    assert products == [] and pagination["stop_reason"] == "empty_page"   # behavior unchanged
    report = pagination["empty_page"]
    assert (report["offset"], report["url"], report["http_status"], report["title"]) == (
        0, "https://www.maicao.cl/perfumes-y-fragancias/", 200, "Perfumes y Fragancias | Maicao")
    assert (report["links"], report["html_links"], report["search_responses"]) == (41, 3, 1)
    assert report["files"] == ["maicao_20261019T000451Z_empty_offset0.html", "maicao_20261019T000451Z_empty_offset0.png"]
    assert (tmp_path / report["files"][0]).read_text(encoding="utf-8").startswith("<html>")
    assert "has no product links" in caplog.text and "status=200" in caplog.text


class BrokenPage:
    url = "https://www.maicao.cl/perfumes-y-fragancias/"

    def title(self): raise RuntimeError("Target page, context or browser has been closed")
    def content(self): raise RuntimeError("closed")
    def screenshot(self, path, full_page): raise RuntimeError("closed")


def test_the_empty_page_report_never_raises(tmp_path) -> None:
    report = empty_page_report(BrokenPage(), None, tmp_path / "maicao_x.json", 0, 0)
    assert report["http_status"] is None and report["files"] == []
    assert report["error"].startswith("RuntimeError: Target page")

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
    def __init__(self, tile_text: str = "ANTONIO BANDERAS\nBlue Seduction Man EDT 200 mL\nAgregar",
                 image: str | None = None) -> None:
        self.tile_text = tile_text
        self.image = image

    def evaluate(self, expression: str) -> dict:
        return {"text": self.tile_text, "image": self.image}

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


MAICAO_IMAGE = ("https://www.maicao.cl/dw/image/v2/BDPM_PRD/on/demandware.static/-/Sites-masterCatalog_Chile/"
                "default/dw0e0c9ad6/images/large/591199-1.jpg")


def test_product_from_link_takes_the_photo_the_tile_script_found() -> None:
    """The photo sits in the tile's image link, not beside the name link: the tile script returns it."""
    scraper = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")
    page_url = "https://www.maicao.cl/perfumes-y-fragancias/"
    assert scraper._product_from_link(FakeLink(image=MAICAO_IMAGE), page_url).image_url == MAICAO_IMAGE
    assert scraper._product_from_link(FakeLink(), page_url).image_url is None


class TwoLinkListingPage(FakeListingPage):
    """As on Maicao: the image link brings the photo, the name link that follows does not."""

    def locator(self, selector):
        urls = self.products_by_offset.get(self.visited[-1], [])
        return FakeLinks([(url, image) for url in urls for image in (MAICAO_IMAGE, None)])


def test_the_name_link_never_drops_the_photo_of_the_image_link(monkeypatch) -> None:
    scraper = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")
    monkeypatch.setattr(scraper, "_product_from_link", lambda link, page_url: ProductRecord(
        name="Perfume 100 ml", brand=None, current_price="$1.000", previous_price=None, volume="100 ml",
        concentration=None, url=link[0], image_url=link[1], availability="available"))
    monkeypatch.setattr(scraper, "_last_offset", lambda page: 0)
    page = TwoLinkListingPage({0: [f"https://www.maicao.cl/p{i}/CLMC_{i}.html" for i in range(3)]})
    products, _ = scraper._scrape_pages(page, {"progress": {}}, None)
    assert [p.image_url for p in products] == [MAICAO_IMAGE] * 3


# Two hits of a product-search response as read on 2026-11-17 (trimmed): the API carries
# every photo, also for the tiles the page has not drawn yet (below the fold).
VENDETTA_GOLD_IMAGE = ("https://www.maicao.cl/dw/image/v2/BDPM_PRD/on/demandware.static/-/Sites-masterCatalog_Chile/"
                       "default/dw0b227e7c/images/large/570233-perfume-hombre-vendetta-gold-edp-100ml.jpg")
SEARCH_WITH_IMAGES = {"total": 446, "hits": [
    {"productId": "CLMC_570233", "price": 29990, "image": {
        "alt": "Perfume Hombre Vendetta Gold EDP 100ml", "disBaseLink": VENDETTA_GOLD_IMAGE,
        "link": VENDETTA_GOLD_IMAGE.replace("/dw/image/v2/BDPM_PRD", "")}},
    {"productId": "CLMC_999001", "price": 9990, "image": {
        "disBaseLink": "https://www.maicao.cl/dw/image/v2/BDPM_PRD/on/demandware.static/-/Sites-masterCatalog_Chile/"
                       "default/dw54117b29/images/large/ND.jpg"}},
    {"productId": "CLMC_999002", "price": 9990},
]}


def test_hit_images_reads_each_photo_and_skips_the_no_photo_placeholder() -> None:
    assert hit_images(SEARCH_WITH_IMAGES) == {"CLMC_570233": VENDETTA_GOLD_IMAGE}
    assert hit_images(None) == {} and hit_images({"hits": None}) == {}


@pytest.mark.parametrize(("url", "usable"), [
    (VENDETTA_GOLD_IMAGE, True),
    (VENDETTA_GOLD_IMAGE + "?sw=307&q=60", True),
    ("https://www.maicao.cl/x/images/large/ND.jpg", False),     # Maicao's "no photo" file
    ("https://www.maicao.cl/x/images/large/ND.jpg?sw=307", False),
    ("data:image/gif;base64,R0lGOD", False),                     # lazy-load stub
    ("/images/large/570233.jpg", False),
    (None, False),
])
def test_usable_image(url, usable) -> None:
    assert (usable_image(url) is not None) is usable


def test_the_search_api_photo_fills_tiles_the_page_has_not_drawn(monkeypatch) -> None:
    scraper = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")
    scraper.api_images = hit_images(SEARCH_WITH_IMAGES)
    monkeypatch.setattr(scraper, "_product_from_link", lambda url, page_url: ProductRecord(
        name="Perfume 100 ml", brand=None, current_price="$1.000", previous_price=None, volume="100 ml",
        concentration=None, url=url, image_url=None, availability="available"))   # no <img> in the tile
    monkeypatch.setattr(scraper, "_last_offset", lambda page: 0)
    page = FakeListingPage({0: ["https://www.maicao.cl/perfume-hombre-vendetta-gold-edp-100ml/CLMC_570233.html",
                                "https://www.maicao.cl/sin-foto/CLMC_999001.html"]})
    products, _ = scraper._scrape_pages(page, {"progress": {}}, None)
    assert [p.image_url for p in products] == [VENDETTA_GOLD_IMAGE, None]


class SlowListingPage(FakeListingPage):
    """As on 2026-11-18: the tiles get their product links only some seconds after loading."""

    def __init__(self, products_by_offset, links_after_ms):
        super().__init__(products_by_offset)
        self.links_after_ms, self.waited = links_after_ms, []

    def goto(self, url, **kwargs):
        super().goto(url)
        self.since_load = 0
        return Response()

    def wait_for_timeout(self, ms):
        self.waited.append(ms)
        self.since_load += ms

    def locator(self, selector):
        if self.since_load < self.links_after_ms:
            return FakeLinks([])
        return super().locator(selector)


def plain_product(url, page_url=None):
    return ProductRecord(name="Perfume 100 ml", brand=None, current_price="$1.000", previous_price=None,
                         volume="100 ml", concentration=None, url=url, image_url=None, availability="available")


def test_a_slow_page_is_read_once_its_product_links_appear(monkeypatch) -> None:
    scraper = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")
    monkeypatch.setattr(scraper, "_product_from_link", plain_product)
    monkeypatch.setattr(scraper, "_last_offset", lambda page: 0)
    page = SlowListingPage({0: [f"https://www.maicao.cl/p{i}/CLMC_{i}.html" for i in range(3)]}, links_after_ms=9000)
    products, pagination = scraper._scrape_pages(page, {"progress": {}}, None)
    assert len(products) == 3 and pagination["stop_reason"] == "short_page"
    assert sum(page.waited) == 9000            # it stopped waiting as soon as the links were there


def test_a_page_still_without_links_after_15_s_is_empty(tmp_path, monkeypatch) -> None:
    from src.scrapers.stores.maicao import scraper as maicao
    scraper = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")
    scraper.search_responses = 1
    page = EmptyListingPage()
    waited = []
    page.wait_for_timeout = waited.append
    products, pagination = scraper._scrape_pages(page, {"progress": {}}, tmp_path / "maicao_x.json")
    assert products == [] and pagination["stop_reason"] == "empty_page"
    assert sum(waited) == maicao.LINKS_WAIT_MS == 15000


def test_a_page_with_links_at_once_waits_only_the_first_look(monkeypatch) -> None:
    from src.scrapers.stores.maicao import scraper as maicao
    scraper = MaicaoScraper("https://www.maicao.cl/perfumes-y-fragancias/")
    monkeypatch.setattr(scraper, "_product_from_link", plain_product)
    monkeypatch.setattr(scraper, "_last_offset", lambda page: 0)
    page = SlowListingPage({0: ["https://www.maicao.cl/p/CLMC_1.html"]}, links_after_ms=0)
    scraper._scrape_pages(page, {"progress": {}}, None)
    assert page.waited == [maicao.FIRST_LOOK_MS]
