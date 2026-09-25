from __future__ import annotations

import re

# A size is a number followed by a unit. The number may be glued to letters
# before it ("X30Ml", "EDT100 Ml", "SP236ML"), so there is no word boundary on
# the left, only "not part of a longer number".
VOLUME_PATTERN = re.compile(
    r"(?<![\d.,])\d+(?:[.,]\d+)?\s*(?:ml|lts?|litros?|l|cc|un)\b", re.IGNORECASE
)


def extract_volume(value: str | None) -> str | None:
    if not value:
        return None
    match = VOLUME_PATTERN.search(value)
    return match.group(0) if match else None
