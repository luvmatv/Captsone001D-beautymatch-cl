"""Clean listing names before matching and embedding them.

repair_mojibake undoes text that a store saved as UTF-8 and served decoded as
Latin-1 or cp1252 (Preunic's "DANCE DIAMONDS\\xc2\\xa0\\xc2": a non-breaking
space and a cut one).

expand_abbreviations: Maicao truncates some names to fit a field ("ARIANA
GR.MOD VAI.SP236ML") and Preunic has a few of its own ("Skr", "P.hilton",
"X236ml"). Rules run in order on lowercased text: structural splits first,
then a dictionary taken from names seen in the catalog. Unknown
abbreviations are left as they are.
"""

from __future__ import annotations

import re

# Runs of characters that are single bytes in cp1252 or Latin-1 above ASCII:
# where mojibake lives. A run is decoded as UTF-8 byte by byte, so a lone
# accent ("é", "ñ") stays as it is: alone it is not valid UTF-8.
_NON_ASCII_BYTE_RUN = re.compile(r"[\u0080-ÿŒœŠšŸŽžƒˆ˜"
                                 r"–—‘-‚“-„†-•…‰‹"
                                 r"›€™]{2,}")
# What is left of a cut sequence: the lead byte of a non-breaking space ("\xc2\xa0")
# without its second byte. A real "Â" is followed by a letter ("L'ÂME").
_STRAY_NBSP_LEAD = re.compile(r"Â(?![^\W\d_])")


def _byte(char: str) -> int:
    try:
        return char.encode("cp1252")[0]
    except UnicodeEncodeError:
        return ord(char)  # U+0080-U+009F: C1 controls, the bytes cp1252 leaves undefined


def _char(byte: int) -> str:
    """The inverse of _byte."""
    try:
        return bytes([byte]).decode("cp1252")
    except UnicodeDecodeError:
        return chr(byte)


def _repair_run(match: re.Match) -> str:
    decoded = bytes(_byte(char) for char in match.group()).decode("utf-8", errors="surrogateescape")
    # a byte that is not part of a UTF-8 sequence comes back as a surrogate: return it to its character
    return "".join(_char(ord(c) - 0xDC00) if 0xDC80 <= ord(c) <= 0xDCFF else c for c in decoded)


def repair_mojibake(text: str) -> str:
    """'DANCE DIAMONDS\\xc2\\xa0\\xc2' -> 'DANCE DIAMONDS', 'CrÃ¨me' -> 'Crème'; other text unchanged."""
    if text.isascii():
        return text
    repaired = _STRAY_NBSP_LEAD.sub(" ", _NON_ASCII_BYTE_RUN.sub(_repair_run, text))
    return " ".join(repaired.split()) if repaired != text else text

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
    text = repair_mojibake(text).lower()
    for pattern, replacement in (*STRUCTURAL_RULES, *ABBREVIATIONS):
        text = re.sub(pattern, replacement, text)
    return " ".join(text.split())
