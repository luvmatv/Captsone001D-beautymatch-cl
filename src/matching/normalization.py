"""Expand store abbreviations in listing names before embedding them.

Maicao truncates some names to fit a field ("ARIANA GR.MOD VAI.SP236ML") and
Preunic has a few of its own ("Skr", "P.hilton", "X236ml"). Rules run in order
on lowercased text: structural splits first, then a dictionary taken from
names seen in the catalog. Unknown abbreviations are left as they are.
"""

from __future__ import annotations

import re

STRUCTURAL_RULES = (
    (r"(?<=[a-z])\.(?=[a-z\d])", " "),        # "gr.mod" -> "gr mod", "sp.236" -> "sp 236"
    (r"(?<=[a-z])(?=\d)", " "),               # "sp236ml" -> "sp 236ml", "than2.0" -> "than 2.0"
    (r"(?<=\d)\s*(?:ml|m)\b", " ml"),          # "236ml" / "100m" -> "236 ml"
    (r"\bx(?= \d)", ""),                      # "x 236 ml" -> " 236 ml" (size prefix)
)

ABBREVIATIONS = (
    (r"\bariana gr\b", "ariana grande"),
    (r"\bgod wom\b", "god is a woman"),
    (r"\bmod vai\b", "mod vanilla"),
    (r"\bmod blu\b", "mod blush"),
    (r"\bmoonl\b", "moonlight"),
    (r"\bswee lik\b", "sweet like candy"),
    (r"\bthan (?=2\.0)", "thank u next "),
    (r"\bdeso\b", "desodorante"),
    (r"\bbod\b", "body"),
    (r"\bsp\b", "spray"),
    (r"\bspay\b", "spray"),
    (r"\bwom\b", "woman"),
    (r"\bw(?= edp\b)", "woman"),
    (r"\bm(?= edp\b)", "man"),
    (r"\bskr\b", "shakira"),
    (r"\bp hilton\b", "paris hilton"),
)


def expand_abbreviations(text: str) -> str:
    text = text.lower()
    for pattern, replacement in (*STRUCTURAL_RULES, *ABBREVIATIONS):
        text = re.sub(pattern, replacement, text)
    return " ".join(text.split())
