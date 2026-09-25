from pathlib import Path

import pandas as pd

from src.vocabulary_seed import MIS_PALABRAS, frequency_words
from src.word_loader import is_valid_token, load_frecuencia, load_mis_palabras, sync_vocabulary
from src.database import initialize_schema, transaction


REQUIRED = [
    "mamá",
    "papá",
    "gato",
    "perro",
    "oso",
    "pez",
    "pato",
    "vaca",
    "rana",
    "lobo",
    "mono",
    "casa",
    "cama",
    "mesa",
    "mano",
    "pie",
    "ojo",
    "boca",
    "agua",
    "pan",
    "sol",
    "luna",
    "rojo",
    "azul",
    "niño",
    "árbol",
    "ratón",
    "león",
]


def test_seed_lists_are_curated_and_valid() -> None:
    assert 90 <= len(MIS_PALABRAS) <= 130
    assert len({word.casefold() for word, _category in MIS_PALABRAS}) == len(MIS_PALABRAS)
    words = {word for word, _category in MIS_PALABRAS}
    assert set(REQUIRED) <= words
    frequent = frequency_words()
    assert len(frequent) == 500
    assert len({word.casefold() for word in frequent}) == 500
    for word in list(words) + frequent:
        assert is_valid_token(word)


def test_loader_keeps_unicode_and_skips_junk(tmp_path: Path) -> None:
    mis = tmp_path / "mis_palabras.xlsx"
    pd.DataFrame(
        [
            ("mamá", "familia", 1),
            ("papá", "familia", 1),
            ("niño", "familia", 1),
            ("árbol", "naturaleza", 1),
            ("ratón", "animales", 1),
            ("león", "animales", 1),
            ("hola!", "otros", 1),
            ("123", "otros", 1),
            ("http://ejemplo.com", "otros", 1),
            ("dos palabras", "otros", 1),
            ("oculto", "otros", 0),
        ],
        columns=["word", "category", "enabled"],
    ).to_excel(mis, index=False, engine="openpyxl")
    freq = tmp_path / "frecuencia_espanol.xlsx"
    pd.DataFrame(
        [(1, "niño", 1), (2, "de", 1), (3, "www.ejemplo.com", 1), (4, "2", 1)],
        columns=["rank", "word", "enabled"],
    ).to_excel(freq, index=False, engine="openpyxl")

    loaded = {entry.word: entry for entry in load_mis_palabras(mis)}
    assert set(loaded) == {"mamá", "papá", "niño", "árbol", "ratón", "león", "oculto"}
    assert loaded["mamá"].category == "familia"
    assert loaded["oculto"].enabled is False
    frequent = load_frecuencia(freq)
    assert [entry.word for entry in frequent] == ["niño", "de"]

    db_path = tmp_path / "programa.db"
    with transaction(db_path) as conn:
        initialize_schema(conn)
        count = sync_vocabulary(conn, tmp_path)
        assert count == 9
        row = conn.execute(
            "SELECT word FROM words WHERE word_key = ? AND source = 'mis_palabras'",
            ("mamá",),
        ).fetchone()
        assert row["word"] == "mamá"
