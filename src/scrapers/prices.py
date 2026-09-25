from __future__ import annotations

import re
from typing import Any

# Returns every element inside a product card whose own text is exactly one price
# ("$13.999"), with whether it is rendered struck through. Unit prices such as
# "$10.999 x 100 ML" and accessibility text such as "precio actual $26.999" are
# not exact matches, so they are skipped.
CARD_PRICES_JS = r"""card => [...card.querySelectorAll('*')]
    .map(element => ({
        element,
        text: [...element.childNodes]
            .filter(node => node.nodeType === Node.TEXT_NODE)
            .map(node => node.textContent)
            .join('')
            .trim(),
    }))
    .filter(({ text }) => /^\$\s?[\d.]+$/.test(text))
    .map(({ element, text }) => ({
        text: text.replace(/\s/g, ''),
        struck: getComputedStyle(element).textDecorationLine.includes('line-through'),
    }))"""

PRICE_PATTERN = re.compile(r"^\$[\d.]+$")

# Written into every scraper JSON. Version 1 (no field) took the first two
# distinct "$" amounts in the card text, which swapped list and sale prices on
# Maicao and sometimes picked the per-100 ml price on Preunic.
PRICE_EXTRACTION_VERSION = 2


def pick_prices(nodes: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Return (current_price, list_price) from CARD_PRICES_JS output.

    Stores render the pre-discount list price struck through and the price the
    customer pays as the first plain price. Any later plain price (for example a
    loyalty-card price) is ignored.
    """
    prices = [node for node in nodes if PRICE_PATTERN.match(node["text"])]
    list_price = next((node["text"] for node in prices if node["struck"]), None)
    current_price = next((node["text"] for node in prices if not node["struck"]), None)
    if current_price is None:
        return list_price, None
    return current_price, list_price
