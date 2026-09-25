"""Load vocabulary from Excel and synchronize it into SQLite.

Excel defines which words exist. It does not define the active programme.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.database import upsert_word
from src.models import SOURCE_FRECUENCIA, SOURCE_MIS_PALABRAS, WordEntry
from src.vocabulary_seed import MIS_PALABRAS, frequency_words

INVALID_CHARS = set(".,;:!?¡¿\"'`/\\@#$%&*()[]{}<>|_=+")


def is_valid_token(word: str) -> bool:
    text = word.strip()
    if not text:
        return False
    if any(char.isspace() for char in text):
        return False
    if any(char.isdigit() for char in text):
        return False
    if any(char in INVALID_CHARS for char in text):
        return False
    lowered = text.casefold()
    if lowered.startswith("http") or "www." in lowered:
        return False
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 1:
        return False
    return True


def load_mis_palabras(path: Path) -> list[WordEntry]:
    frame = pd.read_excel(path, engine="openpyxl")
    _require_columns(frame, ["word", "category", "enabled"], path)
    entries: list[WordEntry] = []
    seen: set[str] = set()
    for record in frame.to_dict(orient="records"):
        raw = _cell_text(record.get("word"))
        if not is_valid_token(raw):
            continue
        key = raw.casefold()
        if key in seen:
            continue
        seen.add(key)
        category = _cell_text(record.get("category")).casefold() or "otros"
        entries.append(
            WordEntry(
                word=raw,
                source=SOURCE_MIS_PALABRAS,
                category=category,
                rank=None,
                enabled=_as_bool(record.get("enabled"), default=True),
            )
        )
    return entries


def load_frecuencia(path: Path) -> list[WordEntry]:
    frame = pd.read_excel(path, engine="openpyxl")
    _require_columns(frame, ["rank", "word", "enabled"], path)
    entries: list[WordEntry] = []
    seen: set[str] = set()
    for record in frame.to_dict(orient="records"):
        raw = _cell_text(record.get("word"))
        if not is_valid_token(raw):
            continue
        key = raw.casefold()
        if key in seen:
            continue
        seen.add(key)
        rank_value = record.get("rank")
        rank = int(rank_value) if rank_value is not None and not _is_missing(rank_value) else None
        entries.append(
            WordEntry(
                word=raw,
                source=SOURCE_FRECUENCIA,
                category=None,
                rank=rank,
                enabled=_as_bool(record.get("enabled"), default=True),
            )
        )
    return entries


def ensure_vocabulary_files(data_dir: Path, *, overwrite: bool = False) -> None:
    """Create the starter workbooks if they are missing. Never overwrite parent edits."""
    data_dir.mkdir(parents=True, exist_ok=True)
    _validate_seed()
    mis_path = data_dir / "mis_palabras.xlsx"
    freq_path = data_dir / "frecuencia_espanol.xlsx"
    if overwrite or not mis_path.exists():
        frame = pd.DataFrame(
            [{"word": word, "category": category, "enabled": 1} for word, category in MIS_PALABRAS]
        )
        frame.to_excel(mis_path, index=False, engine="openpyxl")
    if overwrite or not freq_path.exists():
        words = frequency_words()
        frame = pd.DataFrame(
            [{"rank": index, "word": word, "enabled": 1} for index, word in enumerate(words, start=1)]
        )
        frame.to_excel(freq_path, index=False, engine="openpyxl")


def sync_vocabulary(conn: sqlite3.Connection, data_dir: Path) -> int:
    """Insert or update Excel words. Programme state of existing words is kept."""
    mis_path = data_dir / "mis_palabras.xlsx"
    freq_path = data_dir / "frecuencia_espanol.xlsx"
    entries = load_mis_palabras(mis_path) + load_frecuencia(freq_path)
    for entry in entries:
        upsert_word(
            conn,
            word=entry.word,
            source=entry.source,
            category=entry.category,
            rank=entry.rank,
            enabled=entry.enabled,
        )
    return len(entries)


def _validate_seed() -> None:
    if not 90 <= len(MIS_PALABRAS) <= 130:
        raise RuntimeError("mis_palabras debe contener alrededor de 100 palabras")
    words = frequency_words()
    if not 450 <= len(words) <= 550:
        raise RuntimeError("frecuencia_espanol debe contener alrededor de 500 palabras")
    for word, _category in MIS_PALABRAS:
        if not is_valid_token(word):
            raise RuntimeError(f"Palabra inicial no válida: {word}")
    for word in words:
        if not is_valid_token(word):
            raise RuntimeError(f"Palabra frecuente no válida: {word}")


def _require_columns(frame: pd.DataFrame, columns: list[str], path: Path) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} no tiene las columnas {missing}")


def _cell_text(value: object) -> str:
    if _is_missing(value):
        return ""
    return str(value).strip()


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _as_bool(value: object, default: bool) -> bool:
    if _is_missing(value):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"1", "true", "sí", "si", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default
