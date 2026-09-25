"""Shared fixtures. Tests never touch the repository's data directory."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.database_manager import DatabaseManager  # noqa: E402

MIS_ROWS = [
    ("mamá", "familia", 1),
    ("papá", "familia", 1),
    ("niño", "familia", 1),
    ("tío", "familia", 1),
    ("bebé", "familia", 1),
    ("secreto", "familia", 0),
    ("gato", "animales", 1),
    ("perro", "animales", 1),
    ("oso", "animales", 1),
    ("pez", "animales", 1),
    ("león", "animales", 1),
    ("mano", "cuerpo", 1),
    ("pie", "cuerpo", 1),
    ("ojo", "cuerpo", 1),
    ("boca", "cuerpo", 1),
    ("nariz", "cuerpo", 1),
    ("casa", "casa", 1),
    ("cama", "casa", 1),
    ("mesa", "casa", 1),
    ("silla", "casa", 1),
    ("puerta", "casa", 1),
    ("agua", "comida", 1),
    ("pan", "comida", 1),
    ("leche", "comida", 1),
    ("sopa", "comida", 1),
    ("arroz", "comida", 1),
    ("sol", "naturaleza", 1),
    ("luna", "naturaleza", 1),
    ("árbol", "naturaleza", 1),
    ("ratón", "naturaleza", 1),
    ("río", "naturaleza", 1),
]

FREQ_ROWS = [
    (1, "de", 1),
    (2, "que", 1),
    (3, "el", 1),
    (4, "la", 1),
    (5, "y", 1),
    (6, "piedra", 1),
    (7, "nube", 1),
    (8, "viento", 1),
    (9, "fuego", 1),
    (10, "arena", 1),
]


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    pd.DataFrame(MIS_ROWS, columns=["word", "category", "enabled"]).to_excel(
        folder / "mis_palabras.xlsx", index=False, engine="openpyxl"
    )
    pd.DataFrame(FREQ_ROWS, columns=["rank", "word", "enabled"]).to_excel(
        folder / "frecuencia_espanol.xlsx", index=False, engine="openpyxl"
    )
    return folder


@pytest.fixture
def manager(data_dir: Path) -> DatabaseManager:
    programme = DatabaseManager(data_dir)
    programme.create_database("lectura_test", switch=True)
    return programme
