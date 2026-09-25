from __future__ import annotations

import re

# Checked in order: explicit concentrations win over the generic "colonia"
# (e.g. "King Of Seduction Colonia EDT" is EDT). The loader maps EDC to the
# database value 'cologne'.
CONCENTRATION_PATTERNS = (
    (r"\b(?:eau|agua)\s+de\s+(?:parfum|perfume)\b", "EDP"),
    (r"\beau\s+de\s+toil+et+e\b", "EDT"),
    (r"\b(?:eau\s+de\s+cologne|agua\s+de\s+colonia)\b", "EDC"),
    (r"\bedp\b", "EDP"),
    (r"\bedt\b", "EDT"),
    (r"\bedc\b", "EDC"),
    (r"\bparfum\b", "PARFUM"),
    (r"\bcol[oó]nia\b", "EDC"),
)


def extract_concentration(value: str | None) -> str | None:
    if not value:
        return None
    for pattern, normalized in CONCENTRATION_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            return normalized
    return None
