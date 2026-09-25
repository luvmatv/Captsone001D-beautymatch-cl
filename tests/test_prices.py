from src.scrapers.prices import pick_prices


def test_struck_price_is_list_price_and_first_plain_price_is_current() -> None:
    nodes = [
        {"text": "$13.999", "struck": True},
        {"text": "$10.999", "struck": False},
        {"text": "$9.659", "struck": False},
    ]

    assert pick_prices(nodes) == ("$10.999", "$13.999")


def test_price_without_discount_has_no_list_price() -> None:
    assert pick_prices([{"text": "$22.999", "struck": False}]) == ("$22.999", None)


def test_only_struck_price_is_used_as_current() -> None:
    assert pick_prices([{"text": "$22.999", "struck": True}]) == ("$22.999", None)


def test_no_prices() -> None:
    assert pick_prices([]) == (None, None)
