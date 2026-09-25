from src.display import apply_case, central_letter, middle_index, render_word_html
from src.models import CASE_LOWER, CASE_ORIGINAL, CASE_UPPER, DISPLAY_BLACK, DISPLAY_CENTRAL, DISPLAY_DOMAN_RED


def test_middle_letter_examples() -> None:
    assert middle_index("sol") == 1
    assert central_letter("sol") == "o"
    assert central_letter("gato") == "a"
    assert central_letter("perro") == "r"


def test_spanish_case_keeps_accents() -> None:
    assert apply_case("mamá", CASE_UPPER) == "MAMÁ"
    assert apply_case("papá", CASE_UPPER) == "PAPÁ"
    assert apply_case("niño", CASE_UPPER) == "NIÑO"
    assert apply_case("árbol", CASE_UPPER) == "ÁRBOL"
    assert apply_case("ratón", CASE_UPPER) == "RATÓN"
    assert apply_case("león", CASE_UPPER) == "LEÓN"
    assert apply_case("MAMÁ", CASE_LOWER) == "mamá"
    assert apply_case("Niño", CASE_ORIGINAL) == "Niño"


def test_visual_modes() -> None:
    doman = render_word_html("gato", DISPLAY_DOMAN_RED, CASE_UPPER)
    assert "GATO" in doman
    assert "color:#d00000" in doman
    assert "background:#ffffff" in doman

    central = render_word_html("gato", DISPLAY_CENTRAL, CASE_LOWER)
    assert 'color:#d00000">a</span>' in central
    assert 'color:#111111">g</span>' in central
    assert 'color:#111111">t</span>' in central

    black = render_word_html("sol", DISPLAY_BLACK, CASE_LOWER)
    assert "color:#d00000" not in black
    assert 'color:#111111">sol</span>' in black
    assert "white-space:nowrap" in black
