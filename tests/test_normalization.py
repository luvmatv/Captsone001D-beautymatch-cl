import pytest

from src.matching.normalization import expand_abbreviations


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
    "name",
    ["Perfume Mujer She Is EDP 100 ml", "Silver Eau de Toilette de 100 mL", "Set Body Splash 3x75ml"],
)
def test_regular_names_only_get_whitespace_and_size_normalized(name) -> None:
    expanded = expand_abbreviations(name)
    assert "spray" not in expanded and "grande" not in expanded
    assert expanded.replace(" ", "") == name.lower().replace(" ", "")
