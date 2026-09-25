"""SQLite schema and programme persistence.

Each database file is one reading profile. Connections are short-lived and
multi-step changes run inside a single transaction.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

from src.models import (
    CASE_LOWER,
    DISPLAY_DOMAN_RED,
    PRESENTATION_PURE,
    SOURCE_MIS_PALABRAS,
    ProgrammeState,
    WordStats,
)
from src.statistics import apply_result

SCHEMA_VERSION = "1"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS programme_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    programme_day INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_used TEXT NOT NULL,
    last_calendar_date TEXT NOT NULL,
    suggestion_dismissed_date TEXT,
    words_per_set INTEGER NOT NULL DEFAULT 5,
    max_active_sets INTEGER NOT NULL DEFAULT 5,
    retirement_exposure_target INTEGER NOT NULL DEFAULT 15,
    retirement_min_days INTEGER NOT NULL DEFAULT 5,
    auto_retire INTEGER NOT NULL DEFAULT 0,
    vocabulary_source TEXT NOT NULL DEFAULT 'mis_palabras',
    display_mode TEXT NOT NULL DEFAULT 'doman_red',
    case_mode TEXT NOT NULL DEFAULT 'minusculas',
    presentation_mode TEXT NOT NULL DEFAULT 'presentacion',
    shuffle_within_set INTEGER NOT NULL DEFAULT 1,
    manual_counts_toward_retirement INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS words (
    id INTEGER PRIMARY KEY,
    word TEXT NOT NULL,
    word_key TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT,
    rank INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,
    state TEXT NOT NULL DEFAULT 'AVAILABLE',
    created_at TEXT NOT NULL,
    UNIQUE (source, word_key)
);

CREATE TABLE IF NOT EXISTS word_sets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    state TEXT NOT NULL DEFAULT 'PLANNED',
    kind TEXT NOT NULL DEFAULT 'programme',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    activated_programme_day INTEGER,
    retired_at TEXT,
    retired_programme_day INTEGER
);

CREATE TABLE IF NOT EXISTS set_words (
    set_id INTEGER NOT NULL REFERENCES word_sets(id),
    word_id INTEGER NOT NULL REFERENCES words(id),
    position INTEGER NOT NULL,
    PRIMARY KEY (set_id, word_id),
    UNIQUE (set_id, position)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    set_id INTEGER REFERENCES word_sets(id),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    programme_day INTEGER NOT NULL,
    session_type TEXT NOT NULL,
    counts_toward_retirement INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS presentations (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    word_id INTEGER NOT NULL REFERENCES words(id),
    set_id INTEGER REFERENCES word_sets(id),
    timestamp TEXT NOT NULL,
    programme_day INTEGER NOT NULL,
    display_mode TEXT NOT NULL,
    case_mode TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('exposure', 'correct', 'incorrect'))
);

CREATE TABLE IF NOT EXISTS word_stats (
    word_id INTEGER PRIMARY KEY REFERENCES words(id),
    times_presented INTEGER NOT NULL DEFAULT 0,
    neutral_exposures INTEGER NOT NULL DEFAULT 0,
    correct_count INTEGER NOT NULL DEFAULT 0,
    incorrect_count INTEGER NOT NULL DEFAULT 0,
    retirement_presentations INTEGER NOT NULL DEFAULT 0,
    last_presented TEXT,
    last_evaluated TEXT,
    reinforcement_score REAL NOT NULL DEFAULT 0,
    introduced_at TEXT,
    introduced_programme_day INTEGER,
    retired_at TEXT,
    retired_programme_day INTEGER
);

CREATE INDEX IF NOT EXISTS idx_presentations_day ON presentations(programme_day);
CREATE INDEX IF NOT EXISTS idx_presentations_word ON presentations(word_id);
CREATE INDEX IF NOT EXISTS idx_presentations_set ON presentations(set_id);
CREATE INDEX IF NOT EXISTS idx_sessions_day ON sessions(programme_day);
CREATE INDEX IF NOT EXISTS idx_words_state ON words(state);
CREATE INDEX IF NOT EXISTS idx_sets_state ON word_sets(state, kind, sort_order);
"""


def utc_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(timespec="seconds")


def today_iso() -> str:
    return date.today().isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_schema(conn: sqlite3.Connection) -> None:
    """Create the schema if this database is new. Existing data is left intact."""
    row = _schema_version(conn)
    if row == SCHEMA_VERSION:
        return
    if row is not None:
        raise RuntimeError(f"Versión de esquema no soportada: {row}")
    conn.executescript(SCHEMA_SQL)
    now = utc_now()
    today = today_iso()
    conn.execute(
        """
        INSERT INTO programme_state (
            id, programme_day, created_at, last_used, last_calendar_date,
            words_per_set, max_active_sets, retirement_exposure_target,
            retirement_min_days, auto_retire, vocabulary_source, display_mode,
            case_mode, presentation_mode, shuffle_within_set,
            manual_counts_toward_retirement
        ) VALUES (1, 1, ?, ?, ?, 5, 5, 15, 5, 0, ?, ?, ?, ?, 1, 0)
        """,
        (now, now, today, SOURCE_MIS_PALABRAS, DISPLAY_DOMAN_RED, CASE_LOWER, PRESENTATION_PURE),
    )
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )


def _schema_version(conn: sqlite3.Connection) -> str | None:
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_meta'"
    ).fetchone()
    if exists is None:
        return None
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return None
    return str(row["value"])


def get_state(conn: sqlite3.Connection) -> ProgrammeState:
    row = conn.execute("SELECT * FROM programme_state WHERE id = 1").fetchone()
    if row is None:
        raise RuntimeError("La base no tiene estado de programa")
    return ProgrammeState(
        programme_day=int(row["programme_day"]),
        created_at=str(row["created_at"]),
        last_used=str(row["last_used"]),
        last_calendar_date=str(row["last_calendar_date"]),
        suggestion_dismissed_date=row["suggestion_dismissed_date"],
        words_per_set=int(row["words_per_set"]),
        max_active_sets=int(row["max_active_sets"]),
        retirement_exposure_target=int(row["retirement_exposure_target"]),
        retirement_min_days=int(row["retirement_min_days"]),
        auto_retire=bool(row["auto_retire"]),
        vocabulary_source=str(row["vocabulary_source"]),
        display_mode=str(row["display_mode"]),
        case_mode=str(row["case_mode"]),
        presentation_mode=str(row["presentation_mode"]),
        shuffle_within_set=bool(row["shuffle_within_set"]),
        manual_counts_toward_retirement=bool(row["manual_counts_toward_retirement"]),
    )


def update_state(conn: sqlite3.Connection, **fields: object) -> None:
    if not fields:
        return
    allowed = {
        "programme_day",
        "last_used",
        "last_calendar_date",
        "suggestion_dismissed_date",
        "words_per_set",
        "max_active_sets",
        "retirement_exposure_target",
        "retirement_min_days",
        "auto_retire",
        "vocabulary_source",
        "display_mode",
        "case_mode",
        "presentation_mode",
        "shuffle_within_set",
        "manual_counts_toward_retirement",
    }
    unknown = set(fields) - allowed
    if unknown:
        raise ValueError(f"Campos desconocidos: {sorted(unknown)}")
    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = [int(value) if isinstance(value, bool) else value for value in fields.values()]
    conn.execute(f"UPDATE programme_state SET {assignments} WHERE id = 1", values)


def mark_used(conn: sqlite3.Connection) -> None:
    update_state(conn, last_used=utc_now())


def upsert_word(
    conn: sqlite3.Connection,
    *,
    word: str,
    source: str,
    category: str | None,
    rank: int | None,
    enabled: bool,
) -> int:
    key = word.casefold()
    now = utc_now()
    existing = conn.execute(
        "SELECT id FROM words WHERE source = ? AND word_key = ?",
        (source, key),
    ).fetchone()
    if existing is not None:
        word_id = int(existing["id"])
        conn.execute(
            """
            UPDATE words
            SET word = ?, category = ?, rank = ?, enabled = ?
            WHERE id = ?
            """,
            (word, category, rank, int(enabled), word_id),
        )
        return word_id
    cursor = conn.execute(
        """
        INSERT INTO words (word, word_key, source, category, rank, enabled, state, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'AVAILABLE', ?)
        """,
        (word, key, source, category, rank, int(enabled), now),
    )
    word_id = int(cursor.lastrowid)
    conn.execute("INSERT INTO word_stats (word_id) VALUES (?)", (word_id,))
    return word_id


def load_stats(conn: sqlite3.Connection, word_id: int) -> WordStats:
    row = conn.execute("SELECT * FROM word_stats WHERE word_id = ?", (word_id,)).fetchone()
    if row is None:
        raise KeyError(word_id)
    return WordStats(
        word_id=word_id,
        times_presented=int(row["times_presented"]),
        neutral_exposures=int(row["neutral_exposures"]),
        correct_count=int(row["correct_count"]),
        incorrect_count=int(row["incorrect_count"]),
        retirement_presentations=int(row["retirement_presentations"]),
        last_presented=row["last_presented"],
        last_evaluated=row["last_evaluated"],
        reinforcement_score=float(row["reinforcement_score"]),
        introduced_at=row["introduced_at"],
        introduced_programme_day=row["introduced_programme_day"],
        retired_at=row["retired_at"],
        retired_programme_day=row["retired_programme_day"],
    )


def save_stats(conn: sqlite3.Connection, stats: WordStats) -> None:
    conn.execute(
        """
        UPDATE word_stats SET
            times_presented = ?,
            neutral_exposures = ?,
            correct_count = ?,
            incorrect_count = ?,
            retirement_presentations = ?,
            last_presented = ?,
            last_evaluated = ?,
            reinforcement_score = ?,
            introduced_at = ?,
            introduced_programme_day = ?,
            retired_at = ?,
            retired_programme_day = ?
        WHERE word_id = ?
        """,
        (
            stats.times_presented,
            stats.neutral_exposures,
            stats.correct_count,
            stats.incorrect_count,
            stats.retirement_presentations,
            stats.last_presented,
            stats.last_evaluated,
            stats.reinforcement_score,
            stats.introduced_at,
            stats.introduced_programme_day,
            stats.retired_at,
            stats.retired_programme_day,
            stats.word_id,
        ),
    )


def record_presentation(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    word_id: int,
    set_id: int | None,
    result: str,
    display_mode: str,
    case_mode: str,
) -> None:
    session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise KeyError(session_id)
    state = get_state(conn)
    timestamp = utc_now()
    conn.execute(
        """
        INSERT INTO presentations (
            session_id, word_id, set_id, timestamp, programme_day,
            display_mode, case_mode, result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            word_id,
            set_id,
            timestamp,
            state.programme_day,
            display_mode,
            case_mode,
            result,
        ),
    )
    stats = load_stats(conn, word_id)
    apply_result(stats, result, bool(session["counts_toward_retirement"]), timestamp)
    save_stats(conn, stats)


def clear_programme_progress(conn: sqlite3.Connection) -> None:
    """Remove progress and sets. Vocabulary rows are removed so Excel can be re-synced."""
    conn.execute("DELETE FROM presentations")
    conn.execute("DELETE FROM sessions")
    conn.execute("DELETE FROM set_words")
    conn.execute("DELETE FROM word_sets")
    conn.execute("DELETE FROM word_stats")
    conn.execute("DELETE FROM words")
    today = today_iso()
    update_state(
        conn,
        programme_day=1,
        last_used=utc_now(),
        last_calendar_date=today,
        suggestion_dismissed_date=None,
    )


def backup_database(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = connect(source)
    try:
        dest = sqlite3.connect(destination)
        try:
            src.backup(dest)
        finally:
            dest.close()
    finally:
        src.close()
