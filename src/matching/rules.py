"""Explicit rules that veto a match regardless of embedding similarity.

Embeddings score gender versions and flankers of the same line (The Icon vs
The Icon Elixir, King vs Queen of Seduction) as high as true matches, so these
cases are decided by rules, not by a threshold.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

from src.matching.normalization import expand_abbreviations

MALE, FEMALE = "male", "female"
GENDER_WORDS = {
    "hombre": MALE, "hombres": MALE, "men": MALE, "man": MALE, "him": MALE, "homme": MALE,
    "masculino": MALE, "masculina": MALE, "caballero": MALE, "king": MALE, "he": MALE,
    "mujer": FEMALE, "mujeres": FEMALE, "women": FEMALE, "woman": FEMALE, "her": FEMALE,
    "femme": FEMALE, "femenino": FEMALE, "femenina": FEMALE, "dama": FEMALE, "queen": FEMALE,
    "she": FEMALE,
}

# Words that name a different fragrance of the same line, taken from same-brand
# names in the catalog that differ in exactly that word. Left out on purpose:
# "essence" (Etienne's collection name, omitted by Maicao) and "dream"
# (Preunic shortens "Caramel Dream" to "Caramel").
VARIANT_WORDS = frozenset({
    "elixir", "absolute", "absolu", "absolutely", "intense", "extreme",
    "summerland", "summer", "supreme", "attitude", "splendid", "deluxe", "golden",
    "black", "gold", "silver", "sport", "midnight", "night", "stellar", "diamonds",
    "kiss", "aqua",
})

# Format, packaging, concentration and filler words: they say nothing about
# which fragrance it is. Sizes are numbers and are dropped by the tokenizer.
NEUTRAL_WORDS = frozenset("""
perfume perfumes pefume fragancia fragancias colonia eau de del la le el the for of y and con para by en
edp edt edc parfum toilette toliette toillete toillette cologne spray vaporizador vapo vap natural ml
lt lts litro litros set estuche estche pack regalo mini miniatura tester nuevo new
""".split())

# Set contents are described in either language ("Body Lotion" / "Loción
# Hidratante Cuerpo"); map them to one spelling so they do not look like names.
SYNONYMS = {"corporal": "body", "cuerpo": "body", "locion": "lotion", "hidratante": ""}


def _words(brand: str | None, name: str) -> list[str]:
    text = expand_abbreviations(f"{brand or ''} {name}")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"\bde luxe\b", "deluxe", text)
    words = (SYNONYMS.get(word, word) for word in re.findall(r"[a-z]+", text))
    return [word for word in words if word]


def gender(brand: str | None, name: str) -> str | None:
    found = {GENDER_WORDS[w] for w in _words(brand, name) if w in GENDER_WORDS}
    return found.pop() if len(found) == 1 else None  # none or contradictory -> unknown


def _variant(word: str) -> str | None:
    if word in VARIANT_WORDS:
        return word
    if len(word) >= 6:  # misspelled long variant words ("mignight"); short ones collide ("light"/"night")
        close = [v for v in VARIANT_WORDS if len(v) >= 6 and word_distance(word, v) <= SAME_WORD_MAX_DISTANCE]
        if close:
            return min(close, key=lambda v: word_distance(word, v))
    return None


def variant_words(brand: str | None, name: str) -> frozenset[str]:
    return frozenset(v for v in map(_variant, _words(brand, name)) if v)


def core_words(brand: str | None, name: str) -> frozenset[str]:
    """What identifies the line: everything except gender, format and filler.

    Words of one or two letters are dropped: they are units or fragments
    ("lt", "il"/"ll" Capo) whose edit distance is meaningless.
    """
    return frozenset(
        w for w in _words(brand, name)
        if w not in GENDER_WORDS and w not in NEUTRAL_WORDS and len(w) > 2
    )


# Normalized edit distance (Levenshtein / longer word) up to which two differing
# words count as the same word misspelled. Measured on this catalog: spelling
# variants reach 0.33 (fresh/fresca, lataffa/lattafa, jeans/jean) and the
# closest genuinely different names start at 0.40 (color/flor, rose/rouge).
SAME_WORD_MAX_DISTANCE = 0.35


def levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def word_distance(a: str, b: str) -> float:
    return levenshtein(a, b) / max(len(a), len(b))


def _drop_compounds(joined: list[str], split: list[str]) -> None:
    """Remove words written as one on one side and as two on the other."""
    for word in list(joined):
        for first in split:
            rest = word.removeprefix(first)
            if rest != word and rest in split and rest != first:
                joined.remove(word)
                split.remove(first)
                split.remove(rest)
                break


def different_names(a: tuple[str | None, str], b: tuple[str | None, str]) -> bool:
    """Both names carry their own identifying word that the other lacks.

    "Hotphoria Power" vs "Hotphoria Peace" -> True. Spelling variants
    (jeans/jean), words joined differently (sweettooth / sweet tooth) and a
    word present on one side only (possible omission) -> False.
    """
    only_a = sorted(core_words(*a) - core_words(*b))
    only_b = sorted(core_words(*b) - core_words(*a))
    _drop_compounds(only_a, only_b)
    _drop_compounds(only_b, only_a)
    if not only_a or not only_b:
        return False
    unmatched_b = list(only_b)
    unmatched_a = []
    for word in only_a:
        close = [other for other in unmatched_b if word_distance(word, other) <= SAME_WORD_MAX_DISTANCE]
        if close:
            unmatched_b.remove(min(close, key=lambda other: word_distance(word, other)))
        else:
            unmatched_a.append(word)
    return bool(unmatched_a and unmatched_b)


SET_WORDS = frozenset({"set", "estuche", "estche", "pack", "regalo"})

# (store, brand, name, volume_ml, concentration)
CatalogEntry = tuple[str, str | None, str, int | None, str | None]


def is_set(name: str) -> bool:
    return "+" in name or bool(SET_WORDS & set(_words(None, name)))


class GenderIndex:
    """Lines (same core words) that the catalog sells in more than one gender.

    A line is split when both genders are named somewhere, or when one store
    sells an unmarked bottle next to a gender-marked bottle of the same volume
    and concentration ("The Icon Elixir EDP 50ML" and "The Icon Elixir Women
    Edp 50Ml" on Maicao): there the unmarked one is the other version.
    """

    def __init__(self, listings: Iterable[CatalogEntry]) -> None:
        named: dict[frozenset[str], set[str]] = defaultdict(set)
        shelves: dict[tuple, set[str | None]] = defaultdict(set)
        for store, brand, name, volume_ml, concentration in listings:
            core, listing_gender = core_words(brand, name), gender(brand, name)
            if listing_gender:
                named[core].add(listing_gender)
            if not is_set(name) and volume_ml:
                shelves[(core, store, volume_ml, concentration)].add(listing_gender)
        self._split = {core for core, genders in named.items() if len(genders) > 1}
        self._split |= {
            key[0] for key, genders in shelves.items() if None in genders and len(genders) > 1
        }

    def is_split(self, core: frozenset[str]) -> bool:
        return core in self._split


def veto(
    a: tuple[str | None, str], b: tuple[str | None, str], genders: GenderIndex
) -> str | None:
    """Return why listings a and b cannot be the same product, or None."""
    gender_a, gender_b = gender(*a), gender(*b)
    if gender_a and gender_b and gender_a != gender_b:
        return "gender"
    if bool(gender_a) != bool(gender_b):
        # Only one name states a gender. If the catalog sells this line in more
        # than one gender, the unmarked name may be the other version: veto.
        core = core_words(*a)
        if core == core_words(*b) and genders.is_split(core):
            return "gender"
    if is_set(a[1]) != is_set(b[1]):
        return "presentation"  # a set/estuche is never the same product as a single bottle
    if variant_words(*a) != variant_words(*b):
        return "variant"
    if different_names(a, b):
        return "name"
    return None
