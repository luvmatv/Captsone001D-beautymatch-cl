from datetime import UTC, datetime, timedelta

import pytest

from src.pricing.list_price_checks import (
    MARKET_MARGIN,
    HistoryStatus,
    MarketStatus,
    Offer,
    Reading,
    check_history,
    check_market,
    check_offers,
)


def at(day: str, hour: int = 12) -> datetime:
    return datetime.fromisoformat(f"2026-{day}").replace(hour=hour, tzinfo=UTC)


def offer(store, readings, url=None):
    readings = tuple(Reading(*r) for r in readings)
    return Offer(store, url or f"https://{store}/x", max(readings, key=lambda r: r.scraped_at), readings)


# Real readings (beautymatch, 2026-10-04).
# Maicao, Sabrina Carpenter Caramel Dream EDP 30 ml: the discount ends and
# comes back with the same list price as the undiscounted price.
CARAMEL_DREAM_MAICAO = offer("maicao", [
    (at("09-25"), 22499, 29999, True),
    (at("09-28", 2), 29999, None, True),
    (at("09-28", 13), 29999, None, True),
    (at("09-28", 15), 26999, 29999, True),
    (at("10-03"), 26999, 29999, True),
])
# Beauty Perfumes, Dolce & Gabbana The One For Men EDP 100 ml: a list price
# appeared without the price moving, but the undiscounted reading was out of stock.
THE_ONE_BEAUTYPERFUMES = offer("beautyperfumes", [
    (at("10-02", 18), 59900, None, False),
    (at("10-04", 0), 59900, 79900, True),
])
# Lattafa Eclaire EDP 100 ml: Beauty Perfumes' list price vs Salcobrand's undiscounted price.
ECLAIRE_BEAUTYPERFUMES = offer("beautyperfumes", [(at("10-04", 0), 29900, 69990, True)])
ECLAIRE_SALCOBRAND = offer("salcobrand", [(at("10-02"), 39999, None, True)])


def test_no_list_price_means_nothing_to_check() -> None:
    plain = offer("salcobrand", [(at("10-01"), 39999, None, True), (at("10-02"), 39999, None, True)])
    assert check_history(plain).status == HistoryStatus.NO_LIST_PRICE
    assert check_market(plain, [CARAMEL_DREAM_MAICAO]).status == MarketStatus.NO_LIST_PRICE


def test_a_discount_seen_since_the_first_reading_is_insufficient_data_not_fine() -> None:
    always = offer("preunic", [(at(f"09-{d}"), 8000, 14999, True) for d in range(25, 31)])
    check = check_history(always)
    assert check.status == HistoryStatus.INSUFFICIENT_DATA
    assert (check.reference_price, check.points_in_window, check.undiscounted_points) == (None, 6, 0)
    assert check.observed_from == at("09-25")


def test_list_price_equal_to_the_undiscounted_price_is_consistent() -> None:
    check = check_history(CARAMEL_DREAM_MAICAO)
    assert check.status == HistoryStatus.CONSISTENT
    assert (check.reference_price, check.reference_scraped_at) == (29999, at("09-28", 13))
    assert (check.points_in_window, check.undiscounted_points) == (5, 2)


def test_list_price_above_every_undiscounted_price_is_above_history() -> None:
    raised = offer("beautyperfumes", [(at("10-01"), 59900, None, True), (at("10-02"), 57900, None, True),
                                      (at("10-04"), 59900, 79900, True)])
    check = check_history(raised)
    assert check.status == HistoryStatus.ABOVE_HISTORY
    assert (check.reference_price, check.reference_scraped_at) == (59900, at("10-01"))


def test_an_out_of_stock_reading_is_not_a_reference() -> None:
    check = check_history(THE_ONE_BEAUTYPERFUMES)
    assert check.status == HistoryStatus.INSUFFICIENT_DATA
    assert (check.points_in_window, check.undiscounted_points) == (2, 0)


def test_only_readings_inside_the_window_count() -> None:
    old_regular = offer("maicao", [(at("08-01"), 29999, None, True), (at("09-25"), 22499, 34999, True),
                                   (at("10-03"), 22499, 34999, True)])
    assert check_history(old_regular, window_days=30).status == HistoryStatus.INSUFFICIENT_DATA
    assert check_history(old_regular, window_days=90).status == HistoryStatus.ABOVE_HISTORY
    # both ends of the window are included
    edge = offer("maicao", [(at("10-03") - timedelta(days=30), 34999, None, True), (at("10-03"), 22499, 34999, True)])
    assert check_history(edge, window_days=30).status == HistoryStatus.CONSISTENT


def test_list_price_above_the_market_median() -> None:
    check = check_market(ECLAIRE_BEAUTYPERFUMES, [ECLAIRE_BEAUTYPERFUMES, ECLAIRE_SALCOBRAND])
    assert check.status == MarketStatus.ABOVE_MARKET
    assert (check.reference_price, check.reference_stores, check.percent_above) == (39999, ("salcobrand",), 75.0)


def test_the_median_keeps_one_expensive_store_from_moving_the_reference() -> None:
    listed = offer("preunic", [(at("10-03"), 29999, 38999, True)])
    others = [offer("salcobrand", [(at("10-03"), 25999, None, True)]),
              offer("maicao", [(at("10-03"), 29999, None, True)]),
              offer("beautyperfumes", [(at("10-03"), 59900, None, True)])]
    check = check_market(listed, [listed, *others])
    # Against the maximum (59900) the list price would look normal; the median shows it is 30 % above.
    assert (check.reference_price, check.percent_above, check.status) == (29999, 30.0, MarketStatus.ABOVE_MARKET)
    assert check.reference_stores == ("beautyperfumes", "maicao", "salcobrand")


def test_each_store_counts_once_with_its_lowest_undiscounted_price() -> None:
    listed = offer("beautyperfumes", [(at("10-03"), 9900, 19900, True)])
    others = [offer("salcobrand", [(at("10-03"), 11999, None, True)], url="https://salcobrand/a"),
              offer("salcobrand", [(at("10-03"), 12999, None, True)], url="https://salcobrand/b"),
              offer("preunic", [(at("10-03"), 15999, None, True)])]
    check = check_market(listed, [listed, *others])
    assert check.reference_price == round((11999 + 15999) / 2)


@pytest.mark.parametrize(("list_price", "status"), [
    (round(10000 * (1 + MARKET_MARGIN)), MarketStatus.WITHIN_MARKET),     # exactly the margin: not above
    (round(10000 * (1 + MARKET_MARGIN)) + 1, MarketStatus.ABOVE_MARKET),
])
def test_market_margin_edge(list_price, status) -> None:
    listed = offer("beautyperfumes", [(at("10-03"), 9000, list_price, True)])
    other = offer("salcobrand", [(at("10-03"), 10000, None, True)])
    assert check_market(listed, [listed, other]).status == status


def test_market_needs_another_store_selling_it_available_and_undiscounted() -> None:
    listed = offer("beautyperfumes", [(at("10-03"), 9900, 19900, True)])
    same_store = offer("beautyperfumes", [(at("10-03"), 11900, None, True)], url="https://beautyperfumes/y")
    discounted = offer("maicao", [(at("10-03"), 9000, 12000, True)])
    out_of_stock = offer("salcobrand", [(at("10-03"), 11999, None, False)])
    check = check_market(listed, [listed, same_store, discounted, out_of_stock])
    assert check.status == MarketStatus.INSUFFICIENT_DATA
    assert (check.reference_price, check.reference_stores, check.percent_above) == (None, (), None)


def test_check_offers_runs_both_checks_for_every_offer() -> None:
    results = check_offers([ECLAIRE_BEAUTYPERFUMES, ECLAIRE_SALCOBRAND])
    assert [(o.store, h.status, m.status) for o, h, m in results] == [
        ("beautyperfumes", HistoryStatus.INSUFFICIENT_DATA, MarketStatus.ABOVE_MARKET),
        ("salcobrand", HistoryStatus.NO_LIST_PRICE, MarketStatus.NO_LIST_PRICE),
    ]
