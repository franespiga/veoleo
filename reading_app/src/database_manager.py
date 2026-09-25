"""Profiles: several SQLite programmes share the same Excel vocabulary."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from src.database import (
    backup_database,
    clear_programme_progress,
    initialize_schema,
    mark_used,
    transaction,
    update_state,
)
from src.doman_scheduler import ensure_active_capacity, ensure_planned_sets, initialize_programme
from src.models import (
    CASE_MODES,
    DISPLAY_MODES,
    PRESENTATION_MODES,
    RECREATE_CONFIRMATION,
    RESET_CONFIRMATION,
    VOCABULARY_SOURCES,
)
from src.word_loader import ensure_vocabulary_files, sync_vocabulary

APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = APP_ROOT / "data"
DEFAULT_DATABASE_NAME = "lectura_default.db"
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class DatabaseError(ValueError):
    """A profile operation was refused."""


class DatabaseManager:
    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            # Lets a check run against a copy of data/ without touching the family profile.
            override = os.environ.get("LECTURA_DATA_DIR")
            data_dir = Path(override) if override else DEFAULT_DATA_DIR
        self.data_dir = Path(data_dir)
        self.db_dir = self.data_dir / "databases"
        self.backup_dir = self.data_dir / "backups"
        self.config_path = self.data_dir / "app_config.db"

    def ensure_ready(self) -> Path:
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        ensure_vocabulary_files(self.data_dir)
        self._ensure_config()
        names = self.list_databases()
        if not names:
            self.create_database("lectura_default", switch=True)
            names = self.list_databases()
        active = self.active_name()
        if active not in names:
            self.set_active(names[0])
        path = self.active_path()
        with self.transaction() as conn:
            initialize_schema(conn)
            sync_vocabulary(conn, self.data_dir)
            ensure_planned_sets(conn)
            ensure_active_capacity(conn)
            mark_used(conn)
        return path

    def list_databases(self) -> list[str]:
        if not self.db_dir.exists():
            return []
        return sorted(path.name for path in self.db_dir.glob("*.db") if path.is_file())

    def active_name(self) -> str:
        self._ensure_config()
        with sqlite3.connect(self.config_path) as conn:
            row = conn.execute("SELECT value FROM app_config WHERE key = 'active_database'").fetchone()
        if row is None:
            return ""
        return str(row[0])

    def active_path(self) -> Path:
        name = self.active_name()
        if not name:
            raise DatabaseError("No hay una base de datos activa")
        path = self.db_dir / name
        if not path.is_file():
            raise DatabaseError(f"No existe la base activa: {name}")
        return path

    def set_active(self, name: str) -> None:
        filename = self._filename(name)
        path = self.db_dir / filename
        if not path.is_file():
            raise DatabaseError(f"No existe la base: {filename}")
        self._set_config("active_database", filename)

    def create_database(self, name: str, *, switch: bool = True) -> Path:
        filename = self._filename(name)
        path = self.db_dir / filename
        if path.exists():
            raise DatabaseError(f"Ya existe una base llamada {filename}")
        self.db_dir.mkdir(parents=True, exist_ok=True)
        with transaction(path) as conn:
            initialize_schema(conn)
            sync_vocabulary(conn, self.data_dir)
            initialize_programme(conn)
        if switch:
            self._ensure_config()
            self._set_config("active_database", filename)
        return path

    def backup_active(self) -> Path:
        source = self.active_path()
        destination = self.backup_dir / f"{source.stem}_backup_{_stamp()}.db"
        if destination.exists():
            destination = self.backup_dir / f"{source.stem}_backup_{_stamp(seconds=True)}.db"
        backup_database(source, destination)
        return destination

    def reset_active(self, confirmation: str) -> None:
        if confirmation != RESET_CONFIRMATION:
            raise DatabaseError(f"Escribe {RESET_CONFIRMATION} para restablecer el progreso")
        path = self.active_path()
        with transaction(path) as conn:
            clear_programme_progress(conn)
            sync_vocabulary(conn, self.data_dir)
            initialize_programme(conn)

    def recreate_active(self, confirmation: str) -> Path:
        if confirmation != RECREATE_CONFIRMATION:
            raise DatabaseError(f"Escribe {RECREATE_CONFIRMATION} para recrear la base")
        source = self.active_path()
        self.backup_active()
        source.unlink()
        with transaction(source) as conn:
            initialize_schema(conn)
            sync_vocabulary(conn, self.data_dir)
            initialize_programme(conn)
        return source

    def delete_database(self, name: str, confirmation: str) -> Path:
        filename = self._filename(name)
        if confirmation != filename:
            raise DatabaseError(f"Escribe {filename} para confirmar el borrado")
        names = self.list_databases()
        if filename not in names:
            raise DatabaseError(f"No existe la base: {filename}")
        if len(names) <= 1:
            raise DatabaseError("No se puede eliminar la única base de datos")
        if self.active_name() == filename:
            replacement = next(item for item in names if item != filename)
            self.set_active(replacement)
        source = self.db_dir / filename
        destination = self.backup_dir / f"deleted_{source.stem}_{_stamp(seconds=True)}.db"
        backup_database(source, destination)
        source.unlink()
        return destination

    def update_settings(self, **fields: object) -> None:
        cleaned = _validate_settings(fields)
        with self.transaction() as conn:
            update_state(conn, **cleaned)
            if "vocabulary_source" in cleaned or "words_per_set" in cleaned or "max_active_sets" in cleaned:
                ensure_planned_sets(conn)
                ensure_active_capacity(conn)

    def sync_active(self) -> int:
        with self.transaction() as conn:
            count = sync_vocabulary(conn, self.data_dir)
            ensure_planned_sets(conn)
            ensure_active_capacity(conn)
            return count

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with transaction(self.active_path()) as conn:
            yield conn

    def _ensure_config(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.config_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def _set_config(self, key: str, value: str) -> None:
        self._ensure_config()
        with sqlite3.connect(self.config_path) as conn:
            conn.execute(
                """
                INSERT INTO app_config (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    @staticmethod
    def _filename(name: str) -> str:
        text = name.strip()
        if text.lower().endswith(".db"):
            text = text[:-3]
        if not _NAME.fullmatch(text):
            raise DatabaseError("Usa solo letras, números, guiones y guiones bajos")
        return f"{text}.db"


def _stamp(seconds: bool = False) -> str:
    now = datetime.now()
    if seconds:
        return now.strftime("%Y-%m-%d_%H%M%S")
    return now.strftime("%Y-%m-%d_%H%M")


def _validate_settings(fields: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, value in fields.items():
        if key == "words_per_set":
            number = int(value)  # type: ignore[arg-type]
            if not 3 <= number <= 8:
                raise DatabaseError("Las palabras por set deben estar entre 3 y 8")
            cleaned[key] = number
        elif key == "max_active_sets":
            number = int(value)  # type: ignore[arg-type]
            if not 1 <= number <= 10:
                raise DatabaseError("Los sets activos máximos deben estar entre 1 y 10")
            cleaned[key] = number
        elif key == "retirement_exposure_target":
            number = int(value)  # type: ignore[arg-type]
            if number < 1:
                raise DatabaseError("El objetivo de exposiciones debe ser al menos 1")
            cleaned[key] = number
        elif key == "retirement_min_days":
            number = int(value)  # type: ignore[arg-type]
            if number < 1:
                raise DatabaseError("Los días mínimos deben ser al menos 1")
            cleaned[key] = number
        elif key in {"auto_retire", "shuffle_within_set", "manual_counts_toward_retirement"}:
            cleaned[key] = bool(value)
        elif key == "vocabulary_source":
            if value not in VOCABULARY_SOURCES:
                raise DatabaseError("Fuente de vocabulario no válida")
            cleaned[key] = value
        elif key == "display_mode":
            if value not in DISPLAY_MODES:
                raise DatabaseError("Modo visual no válido")
            cleaned[key] = value
        elif key == "case_mode":
            if value not in CASE_MODES:
                raise DatabaseError("Modo de mayúsculas no válido")
            cleaned[key] = value
        elif key == "presentation_mode":
            if value not in PRESENTATION_MODES:
                raise DatabaseError("Modo de presentación no válido")
            cleaned[key] = value
        else:
            raise DatabaseError(f"Ajuste desconocido: {key}")
    return cleaned


def should_suggest_day_advance(state_last_calendar_date: str, dismissed_date: str | None, today: str) -> bool:
    if today == state_last_calendar_date:
        return False
    if dismissed_date == today:
        return False
    return True
