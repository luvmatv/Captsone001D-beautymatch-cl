from __future__ import annotations

import re

# Checked in order: explicit concentrations win over the generic "colonia"
# (e.g. "King Of Seduction Colonia EDT" is EDT). The loader maps EDC to the
# database value 'cologne'.
CONCENTRATION_PATTERNS = (
    # Also two store typos of "Eau de Parfum": "Eau de Perfum" (Salcobrand) and
    # "Eau The Parfum" (all three stores), which would otherwise read as no
    # concentration and as PARFUM. "The Icon The Parfum" is a name: no "eau".
    (r"\b(?:eau|agua)\s+(?:de|the)\s+(?:parfum|perfume|perfum)\b", "EDP"),
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
