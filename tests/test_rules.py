import pytest

from src.matching.rules import (
    GenderIndex,
    core_words,
    different_names,
    edition_numbers,
    gender,
    identity_key,
    is_generic,
    marker_gender_conflict,
    name_with_gender_markers,
    same_name,
    store_listing_words,
    variant_words,
    veto,
)

# Real listings (2026-10-02): the Beauty Perfumes names carry "(M)/(H)/(U)", the others do not.
BP_ICON_WOMEN = ("beautyperfumes", "Antonio Banderas", "ANTONIO BANDERAS THE ICON 100ML EDP (M)")
BP_ICON_MEN = ("beautyperfumes", "Antonio Banderas", "ANTONIO BANDERAS THE ICON 100ML EDP (H)")
BP_ICON_EDT_200 = ("beautyperfumes", "Antonio Banderas", "ANTONIO BANDERAS THE ICON 200ML EDT (H)")
BP_BESO = ("beautyperfumes", "Agatha Ruiz de la Prada", "AGATHA RUIZ DE LA PRADA BESO 100ML EDT (M)")
BP_TOMMY_NOW = ("beautyperfumes", "Tommy Hilfiger", "TOMMY HILFIGER TOMMY NOW 100ML EDT (H)")
BP_TOMMY_GIRL_NOW = ("beautyperfumes", "Tommy Hilfiger", "TOMMY HILFIGER TOMMY GIRL NOW 100ML EDT (M)")
BP_ECLAIRE = ("beautyperfumes", "Lattafa", "LATTAFA ECLAIRE 100ML EDP (M)")
BP_ASAD = ("beautyperfumes", "Lattafa", "LATTAFA ASAD 100ML EDP (U)")
PREUNIC_ICON = ("preunic", "Antonio Banderas", "Antonio Banderas The Icon EDP 100 Ml")
PREUNIC_ICON_WOMEN = ("preunic", "Antonio Banderas", "Fragancia The Icon Femenino EDP 100 ML")
PREUNIC_ICON_EDT_200 = ("preunic", "Antonio Banderas", "Perfume Hombre Antonio Banderas The Icon EDT 200 Ml")
MAICAO_ICON_EDT_200 = ("maicao", "ANTONIO BANDERAS", "The Icon EDT 200ML")
PREUNIC_BESO = ("preunic", "Agatha Ruiz de la Prada", "Agatha Ruiz De La Prada Perfume Beso EDT 100 Ml")
PREUNIC_BESO_EN_BESO = ("preunic", "Agatha Ruiz de la Prada", "Perfume Mujer Agatha Ruiz de la Prada De Beso en Beso EDT 100 Ml")
PREUNIC_TOMMY_GIRL_NOW = ("preunic", "Tommy Hilfiger", "Perfume Mujer Tommy Girl Now EDT 100 Ml")
PREUNIC_TOMMY_NOW = ("preunic", "Tommy Hilfiger", "Perfume Hombre Tommy Now EDT 100Ml")
SALCOBRAND_ECLAIRE = ("salcobrand", "Lattafa", "Lattafa Eclaire EDP 100ml")
MAICAO_ASAD = ("maicao", "LATTAFA", "Asad M.EDP SP100M")
MARKED_CATALOG = [
    (store, brand, name_with_gender_markers(store, name), volume, concentration)
    for (store, brand, name), volume, concentration in [
        (BP_ICON_WOMEN, 100, "edp"), (BP_ICON_MEN, 100, "edp"), (BP_ICON_EDT_200, 200, "edt"),
        (BP_BESO, 100, "edt"), (BP_TOMMY_NOW, 100, "edt"), (BP_TOMMY_GIRL_NOW, 100, "edt"),
        (BP_ECLAIRE, 100, "edp"), (BP_ASAD, 100, "edp"),
        (PREUNIC_ICON, 100, "edp"), (PREUNIC_ICON_WOMEN, 100, "edp"), (PREUNIC_ICON_EDT_200, 200, "edt"),
        (MAICAO_ICON_EDT_200, 200, "edt"), (PREUNIC_BESO, 100, "edt"), (PREUNIC_BESO_EN_BESO, 100, "edt"),
        (PREUNIC_TOMMY_GIRL_NOW, 100, "edt"), (PREUNIC_TOMMY_NOW, 100, "edt"),
        (SALCOBRAND_ECLAIRE, 100, "edp"), (MAICAO_ASAD, 100, "edp"),
    ]
]
MARKED_GENDERS = GenderIndex(MARKED_CATALOG)


def test_gender_markers_are_read_only_for_the_store_that_uses_them() -> None:
    assert name_with_gender_markers("beautyperfumes", "LATTAFA ECLAIRE 100ML EDP (M)") == "LATTAFA ECLAIRE 100ML EDP mujer"
    assert name_with_gender_markers("beautyperfumes", "LATTAFA ASAD 100ML EDP (U)") == "LATTAFA ASAD 100ML EDP (U)"
    assert name_with_gender_markers("maicao", "Ariana Grande Cloud EDP 30 ML (M)") == "Ariana Grande Cloud EDP 30 ML (M)"


@pytest.mark.parametrize(("a", "b"), [
    (BP_ICON_WOMEN, PREUNIC_ICON),        # the wrong merge (labeled different): the women's 2023 version
    (BP_ICON_MEN, PREUNIC_ICON),          # labeled same: in doubt too, Preunic's name states no gender
    (BP_ICON_EDT_200, MAICAO_ICON_EDT_200),  # labeled same
    (BP_BESO, PREUNIC_BESO),              # labeled same: Preunic sells Beso unmarked and as "Mujer"
    (BP_TOMMY_NOW, PREUNIC_TOMMY_GIRL_NOW),   # the code contradicts the other name's gender word
    (BP_TOMMY_GIRL_NOW, PREUNIC_TOMMY_NOW),
])
def test_a_gender_resting_only_on_a_store_code_sends_the_pair_to_review(a, b) -> None:
    assert marker_gender_conflict(a, b, MARKED_GENDERS) and marker_gender_conflict(b, a, MARKED_GENDERS)


@pytest.mark.parametrize(("a", "b"), [
    (BP_ICON_EDT_200, PREUNIC_ICON_EDT_200),  # the code agrees with "Hombre"
    (BP_ECLAIRE, SALCOBRAND_ECLAIRE),         # line sold in one gender only
    (BP_ASAD, MAICAO_ASAD),                   # "(U)" is not read
    (PREUNIC_ICON, MAICAO_ICON_EDT_200),      # no store code on either side
])
def test_no_doubt_without_a_conflicting_store_code(a, b) -> None:
    assert not marker_gender_conflict(a, b, MARKED_GENDERS)


@pytest.mark.parametrize(("a", "b"), [
    # Salcobrand's brand is "Banderas": "Antonio" in the other name is part of the brand
    (("Antonio Banderas", "Estuche Blue Seduction For Men Eau de Toilette 50 ml + Balsamo After Shave 75 ml"),
     ("Banderas", "Banderas Perfume Estuche Blue Seduction For Men Eau de Toilette 50 ml + Balsamo After Shave 75 ml")),
    (("Antonio Banderas", "Estuche Perfume Mujer Antonio Banderas The Icon Woman EDP 50ml + Loción Corporal 75ml"),
     ("Banderas", "Estuche Perfume The Icon EDP Femenino 50 ml + Loción Corporal  75 ml")),
    # a misspelled brand ("Millionare") next to the right one in the name
    (("Millionare", "Set Millionaire Red 95ml"), ("Millionaire", "Set Millionaire Red 95ml")),
])
def test_words_of_either_brand_are_not_a_name_difference(a, b) -> None:
    assert same_name(a, b) and same_name(b, a)
    assert not different_names(a, b)


@pytest.mark.parametrize("scent", ["Hello", "Peachy", "Sunny", "Happy"])
def test_body_is_not_a_difference_between_two_mists(scent) -> None:
    # real pairs: Preunic "Daise Mist Hello 100 ml" / Salcobrand "Daise Hello Body Mist 100ml"
    a, b = ("Daise", f"Daise Mist {scent} 100 ml"), ("Daise", f"Daise {scent} Body Mist 100ml")
    assert same_name(a, b) and same_name(b, a) and not different_names(a, b)


@pytest.mark.parametrize(("a", "b"), [
    # real pairs labeled same (splash_pairs_v1.csv, chain_pairs_v1.csv); checked against the product photos
    (("PLAISANCE", "Colonia Moments Splash Cologne 250 mL"), ("Plaisance", "Body Splash Moments 250ml")),
    (("PLAISANCE", "Colonia Classic Splash Cologne 250 mL"), ("Plaisance", "Body Splash Classic 250ml")),
    (("Plaisance", "Body Splash Plaisance Hot in Black 250 ml"), ("Plaisance", "Plaisance Splash Hot In Black 250ml")),
    (("Itzy", "Itzy Splash Cozy Vanilla 250 Ml"), ("Itzy", "Body Splash Itzy Cozy Vainilla 250ml")),
])
def test_body_is_not_a_difference_between_two_splashes(a, b) -> None:
    assert same_name(a, b) and same_name(b, a) and not different_names(a, b)


@pytest.mark.parametrize(("a", "b"), [
    # real pairs (matching_candidates_v1.csv): Maicao "Hair & Body Mist" / Preunic "Body Mist Petrizzio", 200 ml both
    (("PETRIZZIO", "Hair & Body Mist Ready To Party"), ("Petrizzio", "Body Mist Petrizzio Ready To Party 200 Ml")),
    (("PETRIZZIO", "Fragancia Hair & Body Mist Caramel"), ("Petrizzio", "Body Mist Petrizzio Caramel 200 Ml")),
    (("PETRIZZIO", "Hair & Body Mist Take a Break"), ("Petrizzio", "Body Mist Petrizzio Take A Break 200 Ml")),
])
def test_hair_is_not_a_difference_between_two_mists(a, b) -> None:
    assert same_name(a, b) and same_name(b, a) and not different_names(a, b)


def test_hair_still_counts_outside_two_mists() -> None:
    # "hair" is optional only between mists; a splash keeps it
    assert not same_name(("Itzy", "Hair Splash Angel 250 ml"), ("Itzy", "Splash Angel 250 ml"))


@pytest.mark.parametrize(("a", "b"), [
    # real set pairs labeled same (sets_pairs_v1.csv): Salcobrand writes the body lotion "BL" / "B.L."
    (("Shakira", "Estuche Perfume Mujer Shakira Fucsia Edp 50Ml + Loción Corporal 75Ml"),
     ("Shakira", "Estuche Shakira Fucsia EDP 50ml + BL 75ml")),
    (("Shakira", "Estuche Perfume Mujer Shakira Dance Edt 50Ml + Loción Corporal 75Ml"),
     ("Shakira", "Estuche Shakira Dance EDT 50ml + BL 75ml")),
    (("Coral", "Coral Eau De Toillete Belle 100Ml + Body Lotion 70Ml"), ("Coral", "Coral Belle 100ml+B.L.70ml")),
    # ... and "Balsamo After Shave" where the other store says "After Shave"
    (("Antonio Banderas", "Estuche Antonio Bandera Diavolo EDT 50Ml + After Shave 75 Ml"),
     ("Antonio Banderas", "Estuche Perfume Diavolo For Men Eau de Toilette 50 ml + Balsamo After Shave 75 ml")),
    (("Antonio Banderas", "Estuche Perfume Hombre Banderas Mediterráneo EDT 50 ml + After Shave 75 ml"),
     ("Banderas", "Banderas Perfume Estuche Mediterráneo Eau de Toilette 50ml + Balsamo After Shave 75ml")),
    (("Antonio Banderas", "Estuche Seduction X Eau de Parfum for Men 50 ml + Balsamo After Shave 75 ml"),
     ("Banderas", "Antonio Banderas Seduction X Man (EDP 50ml + After Shave 75ml)")),
])
def test_set_contents_written_differently_are_the_same_name(a, b) -> None:
    assert same_name(a, b) and same_name(b, a) and not different_names(a, b)


def test_set_contents_still_tell_sets_apart() -> None:
    # real pair labeled different: a cream is not the body lotion, once "B.L." is read
    assert different_names(("Coral", "Set Coral Belle 100 ml + 55 ml + Crema"), ("Coral", "Coral Belle 100ml+B.L.70ml"))
    # "Balsamo" is dropped only before "After Shave"; on its own it is still a word
    assert not same_name(("Nivea", "Set Nivea Men Balsamo 100 ml"), ("Nivea", "Set Nivea Men 100 ml"))
    # "Perfumero" is not read as "Perfume" (pending more brands than Etienne)
    assert not same_name(("Etienne", "Etienne Eau De Parfum Carmin 80 ml + Perfumero 10 ml"),
                         ("Etienne", "Etienne Eau De Parfum Carmin 80ml + Perfume 10ml"))


def test_body_still_counts_when_only_one_name_is_a_mist() -> None:
    # "Body Splash" vs "Mist": "body" is not dropped (only one says "mist")
    assert not same_name(("Daise", "Daise Happy Body Splash 250 ml"), ("Daise", "Daise Mist Happy 100 ml"))


def test_words_joined_differently_are_the_same_name() -> None:
    # real pair (reference_pairs.csv, labeled same): Preunic "Sweettooth" / Maicao "Sweet Tooth"
    a, b = ("Sabrina Carpenter", "EDP Sabrina Carpenter Sweettooth 30ML"), ("SABRINA CARPENTER", "Sabrina Carpenter Sweet Tooth EDP 30 ML")
    assert same_name(a, b) and same_name(b, a)
    # a compound does not hide a word present on one side only
    assert not same_name(("Sabrina Carpenter", "Sweettooth Cherry 30 ml"), ("Sabrina Carpenter", "Sweet Tooth 30 ml"))
    # nor the product type written on one side only (left for review)
    assert not same_name(("Sabrina Carpenter", "Body Mist Sabrina Carpenter Sweettooth 236 ml"),
                         ("SABRINA CARPENTER", "Sabrina Carpenter Sweet Tooth 236 ML"))


def test_perfum_is_filler_like_perfume_and_parfum() -> None:
    # real pair: Salcobrand "Etienne Eau de Perfum Aura Violette" / Maicao "Eau De Parfum Aura Violette"
    assert same_name(("Etienne", "Etienne Eau de Perfum Aura Violette 100 ml"),
                     ("ETIENNE", "Eau De Parfum Aura Violette 100 Ml"))
    assert "perfum" not in core_words("Eminence", "Eminence Eau de Perfum Absolutelly Blue 100 ml")


def test_brand_words_do_not_hide_a_real_name_difference() -> None:
    icon = ("Banderas", "Perfume Hombre The Icon Eau de Toilette 100 ml")
    assert not same_name(("Antonio Banderas", "Antonio Banderas Blue Seduction EDT 100 ml"), icon)
    assert different_names(("Antonio Banderas", "Antonio Banderas Blue Seduction EDT 100 ml"), icon)
    # only the two listings' brand words are dropped: "Agua" is not one of them here
    assert not same_name(("Agatha Ruiz de la Prada", "Agua de Flor EDT 100 ml"), ("Agatha Ruiz de la Prada", "Flor EDT 100 ml"))

CATALOG = [
    ("preunic", "Antonio Banderas", "Antonio Banderas The Icon EDT 100ml - Perfume Hombre", 100, "edt"),
    ("preunic", "Antonio Banderas", "Fragancia The Icon Femenino EDP 50 ML", 50, "edp"),
    ("maicao", "ANTONIO BANDERAS", "The Icon Elixir EDP 50ML", 50, "edp"),
    ("maicao", "ANTONIO BANDERAS", "The Icon Elixir Women Edp 50Ml", 50, "edp"),
    ("preunic", "Quorum", "Estuche Perfume Hombre Quorum 100 Ml + Desodorante 150 Ml", 100, "edt"),
    ("preunic", "Quorum", "QUORUM Eau de Toilette de 100ml", 100, "edt"),
]
GENDERS = GenderIndex(CATALOG)


def test_gender_words() -> None:
    assert gender("Antonio Banderas", "Banderas Perfumes Mujer The Icon Supreme EDP 50ml") == "female"
    assert gender("Antonio Banderas", "Eau de Toilette Blue seduction For Men 100 mL") == "male"
    assert gender("Antonio Banderas", "Queen of Seduction Summerland Eau de Toilette 80 ml") == "female"
    assert gender("Quorum", "QUORUM Eau de Toilette de 100ml") is None


@pytest.mark.parametrize(
    ("brand", "name", "numbers"),
    [
        ("Ariana Grande", "Body Mist Ariana Grande Thank U Next 2.0 236 Ml", {"2.0"}),
        ("ARIANA GRANDE", "ARIANA GR.THAN2.0 SP.236M", {"2.0"}),
        ("ARIANA GRANDE", "ARIANA GR.SWEE.LIK.EDP.30", set()),
        ("Victorio & Lucchino", "Fragancia Mujer Victorio & Lucchino Aguas Florales N°3 Edt 150 Ml", {"3"}),
        ("Victorio & Lucchino", "Fragancia Mujer Victorio & Lucchino Aguas Frutales Nº18 Vitamina Citrica Edt 150 Ml", {"18"}),
        ("Afnan", "Afnan 9Am Dive Unisex 100 ml", {"9am"}),
        ("Billie Eilish", "Perfume Billie Eilish Vol. 1 EDP 30 ml", {"1"}),
        ("Shakira", "Skr Perfume Dance Red Midnight 2021 Edt 50Ml", set()),
        ("Beauty Secret", "Estuche Beauty Secret Body Mist 150 + Body Mist 15 + Body Lotion 120", set()),
        ("Flaño", "Pack Flaño Loción FM 120cc+Desod Spray", set()),
    ],
)
def test_edition_numbers(brand, name, numbers) -> None:
    assert edition_numbers(brand, name) == numbers


def test_different_edition_numbers_are_variants() -> None:
    assert veto(("Ariana Grande", "Body Mist ARIANA GRANDE THANK U NEXT 236 Ml"),
                ("ARIANA GRANDE", "ARIANA GR.THAN2.0 SP.236M"), GENDERS) == "variant"
    assert veto(("Victorio & Lucchino", "Aguas Florales N°3 Edt 150 Ml"),
                ("VICTORIO & LUCCHINO", "Aguas Florales N°4 Edt 150 Ml"), GENDERS) == "variant"


@pytest.mark.parametrize(
    ("brand", "name", "generic"),
    [
        ("Shakira", "Perfume Shakira 50 ml", True),
        ("Natalie", "Body Mist Natalie 250 Ml", True),
        ("PARIS HILTON", "Perfume Corporal Body Mist Spray 236 mL", True),
        ("Eminence", "Perfume EDC", True),
        ("HALLOWEEN", "Eau De Toilette con Vaporizador 30 mL", True),
        ("Benjamin Vicuña", "Perfume Mujer She Is EDP 100 ml", False),
        ("Natalie", "Natalie Body Mist Kokone", False),
        ("Etienne", "Perfume Etienne Essence EDP 100 Ml", True),  # collection word only
        ("BUBU", "Body Mist 1981 250 Ml", False),
    ],
)
def test_is_generic(brand, name, generic) -> None:
    assert is_generic(brand, name) is generic


def test_generic_name_on_one_side_is_vetoed_but_not_on_both() -> None:
    assert veto(("Shakira", "Perfume Shakira 50 ml"),
                ("SHAKIRA", "Perfume Mujer Rojo EDP 50ml"), GENDERS) == "generic"
    assert veto(("Benjamin Vicuña", "Perfume Mujer She Is EDP 100 ml"),
                ("BENJAMIN VICUÑA", "Perfume Mujer She Is EDP 100 ml"), GENDERS) is None


def test_name_gender_words_count_as_names() -> None:
    assert veto(("Benjamin Vicuña", "Perfume Mujer She Is EDP 100 ml"),
                ("BENJAMIN VICUÑA", "Perfume Union EDP 100 ml"), GENDERS) == "name"


def test_collection_words_are_ignored_for_their_brand_only() -> None:
    assert core_words("Etienne", "Etienne essence eau de parfum rouge 100 ML") == \
        core_words("ETIENNE", "Eau De Parfum Spray Rouge 100 mL")
    assert core_words("Sabrina Carpenter", "EDP Sabrina Carpenter Caramel 30ML") == \
        core_words("SABRINA CARPENTER", "Sabrina Carpenter Caramel Dream EDP 30 ML")
    assert "dream" in core_words("Beauty Secret", "Beauty Secret Dream Body Mist")


def test_litre_unit_is_not_a_name() -> None:
    # "1Lt" must not count as a name word; what is left is a one-sided extra (ambiguous)
    assert not different_names(
        ("Bellekiss", "Bellekiss Colonia 1Lt Fresh"),
        ("BELLEKISS", "Colonia Fresca Floral Familiar 1000 mL"),
    )


def test_variant_words_normalize_de_luxe() -> None:
    assert variant_words("Millionaire", "Eau de toilette Gold de Luxe") == {"gold", "deluxe"}


@pytest.mark.parametrize(
    ("a", "b", "reason"),
    [
        (("Antonio Banderas", "Perfume Hombre Banderas Icon Man Supreme 50 ML"),
         ("ANTONIO BANDERAS", "Banderas Perfumes Mujer The Icon Supreme EDP 50ml"), "gender"),
        (("Antonio Banderas", "Banderas Hombre King of Seduction Summerland Eau de Toilette 100 ml"),
         ("ANTONIO BANDERAS", "Queen of Seduction Summerland Eau de Toilette 80 ml"), "gender"),
        (("Antonio Banderas", "Perfume The Icon Elixir Antonio Banderas Edp 50 Ml"),
         ("ANTONIO BANDERAS", "The Icon Elixir Women Edp 50Ml"), "gender"),
        (("Antonio Banderas", "Perfume The Icon Elixir Antonio Banderas Edp 50 Ml"),
         ("ANTONIO BANDERAS", "Perfume The Icon New Eau De Parfum 50 mL"), "variant"),
        (("Antonio Banderas", "Eau de Toilette KING OF SEDUCTION"),
         ("ANTONIO BANDERAS", "King Seduction Absolute Eau de Toilette de 50 mL"), "variant"),
        # one side unmarked, catalog carries both genders of The Icon
        (("Antonio Banderas", "Fragancia The Icon Femenino EDP 50 ML"),
         ("ANTONIO BANDERAS", "The Icon EDT 200ML"), "gender"),
        (("Eminence", "Set Eminence Sport Edp 100Ml + Desodorante Spray 160Ml"),
         ("EMINENCE", "Perfume Sport EDP 100 ml"), "presentation"),
        (("Antonio Banderas", "Estuche Antonio Banderas Her Secret Perfume 50ml Spray"),
         ("ANTONIO BANDERAS", "Her Secret Eau de Toilette 50 mL"), "presentation"),
        (("Plaisance", "Perfume Plaisance Hotphoria Power EDP 80 Ml"),
         ("PLAISANCE", "Perfume Hotphoria Peace EDP 80ml"), "name"),
        (("Jean Les Pins", "Fragancia Jean Les Pins Agua de Gardenia EDT 100 ml"),
         ("JEAN LES PINS", "Fragancia Agua de Magnolia EDT 100 ml"), "name"),
        (("Etienne", "Perfume Etienne Essence Rose 100 Ml"),
         ("ETIENNE", "Perfume Rouge 100ml"), "name"),
        (("Benjamin Vicuña", "Perfume Hombre He Is EDP 100 ml"),
         ("BENJAMIN VICUÑA", "Perfume Mujer She Is EDP 100 ml"), "gender"),
        # "Mignight" is a misspelled flanker word
        (("Shakira", "Estuche Perfume Mujer Shakira Dance Mignight Edt 50Ml + Loción Corporal 75Ml"),
         ("SHAKIRA", "Dance Eau De Toilette Natural Spray 50 mL + Body Lotion 75 mL"), "variant"),
    ],
)
def test_veto_blocks_gender_versions_and_flankers(a, b, reason) -> None:
    assert veto(a, b, GENDERS) == reason


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (("Antonio Banderas", "Perfume The Icon Elixir Antonio Banderas Edp 50 Ml"),
         ("ANTONIO BANDERAS", "The Icon Elixir EDP 50ML")),
        (("Antonio Banderas", "Perfume Hombre Banderas Icon Man Supreme 50 ML"),
         ("ANTONIO BANDERAS", "Banderas Perfume Hombre The Icon Supreme EDP 50ml")),
        # gender only on one side, and the catalog has no female Quorum
        (("Quorum", "Perfume Hombre Quorum EDT 100 ml"),
         ("QUORUM", "QUORUM Eau de Toilette de 100ml")),
        (("Sabrina Carpenter", "EDP Sabrina Carpenter Caramel 30ML"),
         ("SABRINA CARPENTER", "Sabrina Carpenter Caramel Dream EDP 75 ML")),
        (("Eminence", "Set Eminence Sport Edp 100Ml + Desodorante Spray 160Ml"),
         ("EMINENCE", "Set Sport Eau de Parfum 100 mL + Desodorante Spray 160 mL")),
        # spelling variant (jeans/jean) and a word joined differently
        (("Jean Les Pins", "Fragancia Mujer Jeans Les Pins Agua de Jazmín EDT 100 ml"),
         ("JEAN LES PINS", "Fragancia Agua de Jazmin EDT 100ml")),
        (("Sabrina Carpenter", "EDP Sabrina Carpenter Sweettooth 30ML"),
         ("SABRINA CARPENTER", "Sabrina Carpenter Sweet Tooth EDP 30 ML")),
        (("Sabrina Carpenter", "Body Mist Sabrina Carpenter Sweettooth 236 ml"),
         ("SABRINA CARPENTER", "Sabrina Carpenter Sweet Tooth 236 ML")),
        (("Piero Butti", "Piero Butti Eau de Toilette il Capo 100 ml"),
         ("PIERO BUTTI", "Perfume de Hombre ll Capo 100 mL")),
        (("Antonio Banderas", "Estuche Banderas Her Golden Secret 50ml + Body Lotion 75ml"),
         ("ANTONIO BANDERAS", "Her Golden Secret Eau De Toilette 50 mL+ Loción Hidratante Cuerpo 75 mL")),
        (("Shakira", "Estuche Perfume Mujer Shakira Dance Edt 50Ml + Loción Corporal 75Ml"),
         ("SHAKIRA", "Dance Eau De Toilette Natural Spray 50 mL + Body Lotion 75 mL")),
    ],
)
def test_veto_allows_same_product_written_differently(a, b) -> None:
    assert veto(a, b, GENDERS) is None


# Real names (2026-10-04) of a store's two listings that one identity used to join.
@pytest.mark.parametrize(("store", "brand", "one", "other"), [
    ("dperfumes", "Jean Paul Gaultier", "So Scandal! Eau de Parfum 80 ml", "Scandal Eau de Parfum 80 ml"),
    ("dperfumes", "Hugo Boss", "Hugo XY Eau de Toilette 100 ml", "Hugo XX Eau de Toilette 100 ml"),
    ("dperfumes", "Dolce & Gabbana", "Q Eau de Parfum 100 ml", "K Eau de Parfum 100 ml"),
    ("dperfumes", "Xerjoff", "Cruz del Sur I Parfum 50 ml", "Cruz del Sur II Parfum 50 ml"),
    ("beautyperfumes", "Afnan", "AFNAN 9 AM POUR FEMME 100ML EDP (M)", "AFNAN 9 PM POUR FEMME 100ML EDP (M)"),
    ("beautyperfumes", "Paco Rabanne", "PACO RABANNE PACO 100ML EDT (H)", "PACO RABANNE XS 100ML EDT (H)"),
    # Beauty Perfumes' codes: the women's and the men's version of a line
    ("beautyperfumes", "Antonio Banderas", "ANTONIO BANDERAS THE ICON 100ML EDP (M)",
     "ANTONIO BANDERAS THE ICON 100ML EDP (H)"),
    ("beautyperfumes", "Dolce & Gabbana", "DOLCE & GABBANA LIGHT BLUE 100ML EDT (H)",
     "DOLCE & GABBANA LIGHT BLUE 100ML EDT (M)"),
])
def test_identity_tells_a_stores_products_apart(store, brand, one, other) -> None:
    assert identity_key(brand, one, store) != identity_key(brand, other, store)


def test_identity_reads_codes_only_with_the_store() -> None:
    women, men = BP_ICON_WOMEN[2], BP_ICON_MEN[2]
    assert identity_key("Antonio Banderas", women, "beautyperfumes")[2] == "female"
    assert identity_key("Antonio Banderas", women)[2] is None  # no store: the code is not read


@pytest.mark.parametrize(("brand", "one", "other"), [
    # what a store writes differently for one product still gives one identity
    ("Victoria's Secret", "VICTORIA´S SECRET BOMBSHELL 100ML EDP", "Victoria's Secret Bombshell EDP 100 ml"),
    ("Lattafa", "LATTAFA ASAD 100ML EDP (U)", "Lattafa Asad EDP 100 ml"),
    ("Ariana Grande", "Ariana Grande Cloud 236 ML Body Mist (M)", "Cloud Body Mist 236 ml"),
])
def test_noise_short_words_stay_out_of_the_identity(brand, one, other) -> None:
    assert identity_key(brand, one)[1] == identity_key(brand, other)[1]


# The audit of 2026-10-04: a store's two listings with one product key (real names).
@pytest.mark.parametrize(("brand", "volume", "one", "other"), [
    ("Dior", 100, "Eau Sauvage Eau de Toilette 100 ml – Dior", "Sauvage Eau de Toilette 100 ml – Dior"),
    ("Creed", 100, "Aventus Cologne Eau de Parfum 100 ml – Creed", "Aventus Eau de Parfum 100 ml – Creed"),
    ("Burberry", 100, "Her Eau de Parfum 100 ml – Burberry", "Burberry for Women Eau de Parfum 100 ml – Burberry"),
    ("Maison Margiela", 7, "Set Miniaturas Replica – 2 x 7 ml – Maison Margiela",
     "Set Miniaturas Replica 5 x 7 ml – Maison Margiela"),
    ("Dolce & Gabbana", 100, "The One For Men 2025 Eau de Parfum 100 ml – Dolce & Gabbana",
     "The One for Men Eau de Parfum 100 ml – Dolce & Gabbana"),
    ("Calvin Klein", 100, "CALVIN KLEIN CK ONE SUMMER 2021 100ML EDT (U)", "CALVIN KLEIN CK ONE SUMMER 2019 100ML EDT (U)"),
    ("Lattafa", 20, "LATTAFA PRIDE GIFT SET COLLECTION NO.3 5*20ML (U)", "LATTAFA PRIDE GIFT SET COLLECTION NO.5 5*20ML (U)"),
    ("Fragrance World", 100, "FRAGRANCE WORLD LA UNO MILLION EDP 100ML (H)",
     "FRAGRANCE WORLD LA UNO MILLION LE PARFUM EDP 100ML (H)"),
    ("Fragrance World", 50, "FRAGRANCE WORLD SCANDANT LE PARFUM BELLE CELINE 50ML EDP (M)",
     "FRAGRANCE WORLD SCANDANT BELLE CELINE EDP 50ML (M)"),
    ("Fragrance World", 100, "FRAGRANCE WORLD UR WAY PARFUM 100ML EDP (M)", "FRAGRANCE WORLD UR WAY 100ML EDP (M)"),
    ("Maison Alhambra", 100, "MAISON ALHAMBRA YEAH 100ML EDP (H)", "MAISON ALHAMBRA YEAH MAN PARFUM 100ML EDP (U)"),
    ("Halloween", 125, "HALLOWEEN HALLOWEEN MAN 125ML EDT (H)", "HALLOWEEN HALLOWEEN MAN X 125ML EDT (H)"),
])
def test_store_listing_words_tell_a_stores_products_apart(brand, volume, one, other) -> None:
    assert store_listing_words(brand, one, volume) != store_listing_words(brand, other, volume)


@pytest.mark.parametrize(("brand", "volume", "one", "other"), [
    # a store listing one product twice, written differently
    ("Itzy", 250, "Body Splash Itzy Fantasy 250 ml", "Body Splash Fantasy 250ml"),
    ("Coral", 100, "Perfume Coral EDT Belle 100 ml", "Coral Edt Belle 100Ml"),
    ("Eminence", 100, "Eminence Eau The Parfum Absolutely Blue 100 ml", "Fragancia Eminence Absolutely Blue EDP 100ml"),
    ("Millionaire", None, "MILLIONAIRE EAU DE PARFUM TITANIUM DELUXE", "Eau de perfum titanium deluxe"),
    ("Antonio Banderas", 50,
     "Estuche Blue Seduction For Men Eau de Toilette 50 ml + Balsamo After Shave 75 ml",
     "Banderas Hombre Estuche Blue Seduction For Men Eau de Toilette 50 ml + Balsamo After Shave 75 ml"),
    ("Antonio Banderas", 50,
     "Estuche Perfume Mujer Antonio Banderas The Icon Woman EDP 50ml + Loción Corporal 75ml",
     "Estuche Pefume Mujer Antonio Banderas The Icon Woman Edp 50 Ml + Loción Corporal For Women 75 Ml"),
    ("Flaño", 50, "Pack Flaño Loción FM 50cc+Jabón", "Estuche Flaño Loción FM 50cc+Jabón"),
    ("Tommy Hilfiger", 30, "Tommy Hilfiger Tommy Girl 30ml", "Perfume Tommy Girl Tommy Hilfiger 30ml"),
    ("Cacharel", 100, "CACHAREL AMOR AMOR 100ML + 30ML EDT (M) SET", "CACHAREL AMOR AMOR 100ML + 30Ml EDT (M) SET"),
    ("Animale", 100, "Animale Animale for Men Eau de Toilette 100 ml – Animale",
     "Animale for Men Eau de Toilette 100 ml – Animale"),
])
def test_store_listing_words_keep_a_store_listing_twice_as_one(brand, volume, one, other) -> None:
    assert store_listing_words(brand, one, volume) == store_listing_words(brand, other, volume)
