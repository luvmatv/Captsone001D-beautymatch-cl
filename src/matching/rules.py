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
    "masculino": MALE, "masculina": MALE, "caballero": MALE, "king": MALE,
    "mujer": FEMALE, "mujeres": FEMALE, "women": FEMALE, "woman": FEMALE, "her": FEMALE,
    "femme": FEMALE, "femenino": FEMALE, "femenina": FEMALE, "dama": FEMALE, "queen": FEMALE,
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
edp edt edc parfum toilette toliette toillete cologne spray vaporizador vapo vap natural ml
set estuche estche pack regalo mini miniatura tester nuevo new
""".split())


def _words(brand: str | None, name: str) -> list[str]:
    text = expand_abbreviations(f"{brand or ''} {name}")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"\bde luxe\b", "deluxe", text)
    return re.findall(r"[a-z]+", text)


def gender(brand: str | None, name: str) -> str | None:
    found = {GENDER_WORDS[w] for w in _words(brand, name) if w in GENDER_WORDS}
    return found.pop() if len(found) == 1 else None  # none or contradictory -> unknown


def variant_words(brand: str | None, name: str) -> frozenset[str]:
    return frozenset(w for w in _words(brand, name) if w in VARIANT_WORDS)


def core_words(brand: str | None, name: str) -> frozenset[str]:
    """What identifies the line: everything except gender, format and filler."""
    return frozenset(
        w for w in _words(brand, name)
        if w not in GENDER_WORDS and w not in NEUTRAL_WORDS and len(w) > 1
    )


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
    if variant_words(*a) != variant_words(*b):
        return "variant"
    return None
