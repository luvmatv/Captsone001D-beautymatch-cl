import pytest

from src.matching.normalization import expand_abbreviations, repair_mojibake


@pytest.mark.parametrize(
    ("raw", "repaired"),
    [
        # Preunic, 2026-10-20: a UTF-8 non-breaking space read as Latin-1, then a cut one
        ("Eau de Toilette DANCE DIAMONDSÂ Â", "Eau de Toilette DANCE DIAMONDS"),
        ("CrÃ¨me BrulÃ©e", "Crème Brulée"),
        ("NiÃ±a Bonita", "Niña Bonita"),
        ("Born in Romaâ\u0084¢", "Born in Roma™"),        # C1 bytes kept as Latin-1
        ("Cocoâ€™s Mademoiselle", "Coco’s Mademoiselle"),  # read as cp1252
    ],
)
def test_repair_mojibake(raw, repaired) -> None:
    assert repair_mojibake(raw) == repaired


@pytest.mark.parametrize(
    "name",
    ["Jazmín de España EDT", "L'Âme Chanel", "Chanel N°5 ®", "¿Quién? ¡Ya!",
     "Agua de Colonia 1000 ml", "Café à la crème", "Ámbar Nuit"],
)
def test_names_without_mojibake_are_unchanged(name) -> None:
    assert repair_mojibake(name) == name


def test_embeddings_see_the_repaired_name() -> None:
    assert expand_abbreviations("DANCE DIAMONDSÂ Â Edt 50Ml") == "dance diamonds edt 50 ml"


@pytest.mark.parametrize(
    ("raw", "expanded"),
    [
        ("ARIANA GR.MOD VAI.SP236ML", "ariana grande mod vanilla spray 236 ml"),
        ("ARIANA GR.GOD WOM SP236ML", "ariana grande god is a woman spray 236 ml"),
        ("ARIANA GR.MOD BLU.SP236ML", "ariana grande mod blush spray 236 ml"),
        ("ARIANA GR.MOONL.SP.236ML", "ariana grande moonlight spray 236 ml"),
        ("ARIANA GR.SWEE.LIK.EDP.30", "ariana grande sweet like candy edp 30"),
        ("ARIANA GR.THAN2.0 SP.236M", "ariana grande thank u next 2.0 spray 236 ml"),
        ("Yara W.EDP SP100M", "yara woman edp spray 100 ml"),
        ("Asad M.EDP SP100M", "asad man edp spray 100 ml"),
        ("Armaf Mand.Deso.Bod.200ML", "armaf mand desodorante body 200 ml"),
        ("Skr Perfume Dance Red Midnight 2021 Edt 50Ml", "shakira perfume dance red midnight 2021 edt 50 ml"),
        ("P.hilton Body Mist X236ml Can Can", "paris hilton body mist 236 ml can can"),
        ("Ariana Grande Thank U Next Body Spay 236ml (M)", "ariana grande thank u next body spray 236 ml (m)"),
    ],
)
def test_expand_abbreviations(raw, expanded) -> None:
    assert expand_abbreviations(raw) == expanded


@pytest.mark.parametrize(
    ("raw", "expanded"),
    [
        # an "x" after a word is part of the name (real names, run 58)
        ("HALLOWEEN HALLOWEEN MAN X 125ML EDT (H)", "halloween halloween man x 125 ml edt (h)"),
        ("HALLOWEEN MAN X 125 ML EDT JESUS DEL POZO", "halloween man x 125 ml edt jesus del pozo"),
        ("HUGO BOSS SUPERMAN X 125ML EDP (H)", "hugo boss superman x 125 ml edp (h)"),
        # a pack count is not
        ("Discovery Set 3 x 15 ml – Xerjoff", "discovery set 3 15 ml – xerjoff"),
        ("LATTAFA YARA COLLECTION 25ML X 4 (M) SET", "lattafa yara collection 25 ml 4 (m) set"),
        ("millionaire edp deluxe collection 30ml x 3", "millionaire edp deluxe collection 30 ml 3"),
    ],
)
def test_an_x_is_dropped_only_as_a_size_prefix_or_a_pack_count(raw, expanded) -> None:
    assert expand_abbreviations(raw) == expanded


def test_man_and_man_x_no_longer_read_alike() -> None:
    # dropping the "x" gave both the same text and embedding: an exact tie (runs 56-58)
    assert expand_abbreviations("HALLOWEEN MAN X 125 ML EDT") != expand_abbreviations("HALLOWEEN MAN 125 ML EDT")


@pytest.mark.parametrize(
    "name",
    ["Perfume Mujer She Is EDP 100 ml", "Silver Eau de Toilette de 100 mL", "Set Body Splash 3x75ml"],
)
def test_regular_names_only_get_whitespace_and_size_normalized(name) -> None:
    expanded = expand_abbreviations(name)
    assert "spray" not in expanded and "grande" not in expanded
    assert expanded.replace(" ", "") == name.lower().replace(" ", "")
