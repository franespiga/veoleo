"""Doman programme: thematic sets, programme days, retirement, replacement.

The unit of teaching is a set, not an independently scheduled flashcard.
Correct and incorrect marks never move a word between programme sets.
"""

from __future__ import annotations

import random
import sqlite3

from src.database import get_state, load_stats, record_presentation, save_stats, update_state, utc_now
from src.models import (
    KIND_MANUAL,
    KIND_PROGRAMME,
    KIND_REINFORCEMENT,
    REINFORCEMENT_THRESHOLD,
    SESSION_MANUAL,
    SESSION_NORMAL,
    SESSION_REINFORCEMENT,
    SET_ACTIVE,
    SET_PLANNED,
    SET_RETIRED,
    SOURCE_AMBAS,
    SOURCE_FRECUENCIA,
    SOURCE_MIS_PALABRAS,
    WORD_ACTIVE,
    WORD_RETIRED,
)
from src.statistics import retirement_eligible
from src.vocabulary_seed import FUNCTION_WORD_SET

CATEGORY_PRIORITY = [
    "familia",
    "animales",
    "cuerpo",
    "casa",
    "comida",
    "juguetes",
    "naturaleza",
    "colores",
    "acciones",
    "otros",
]


def target_active_sets(programme_day: int, max_active_sets: int) -> int:
    if programme_day < 1:
        raise ValueError("El día del programa empieza en 1")
    if max_active_sets < 1:
        raise ValueError("Debe haber al menos un set activo")
    return min(programme_day, max_active_sets)


def category_sort_key(category: str | None) -> tuple[int, str]:
    name = (category or "otros").casefold()
    if name in CATEGORY_PRIORITY:
        return (CATEGORY_PRIORITY.index(name), name)
    return (len(CATEGORY_PRIORITY), name)


def display_category(category: str) -> str:
    text = category.strip()
    if not text:
        return "Otros"
    return text[:1].upper() + text[1:]


def initialize_programme(conn: sqlite3.Connection) -> None:
    """Plan thematic sets and activate the day-1 quota. Safe to call again."""
    ensure_planned_sets(conn)
    ensure_active_capacity(conn)


def ensure_planned_sets(conn: sqlite3.Connection) -> int:
    """Create missing programme sets from words that have never joined a programme set."""
    state = get_state(conn)
    created = 0
    if state.vocabulary_source in {SOURCE_MIS_PALABRAS, SOURCE_AMBAS}:
        created += _plan_category_sets(conn, state.words_per_set)
    if state.vocabulary_source in {SOURCE_FRECUENCIA, SOURCE_AMBAS}:
        created += _plan_frequency_sets(conn, state.words_per_set)
    return created


def ensure_active_capacity(conn: sqlite3.Connection, *, auto_replace: bool = False) -> None:
    """Fill up to the day's target.

    Eligible sets are retired only when ``auto_replace`` is set, which the day
    advance uses. Opening the app must not silently retire sets.
    """
    state = get_state(conn)
    target = target_active_sets(state.programme_day, state.max_active_sets)
    if auto_replace and state.auto_retire and _active_programme_count(conn) >= target:
        while True:
            eligible = eligible_set_ids(conn)
            if not eligible:
                break
            retire_set(conn, eligible[0], replace=False)
    while _active_programme_count(conn) < target:
        nxt = _next_planned_set_id(conn)
        if nxt is None:
            break
        activate_set(conn, nxt)


def advance_programme_day(conn: sqlite3.Connection, *, today: str | None = None) -> int:
    state = get_state(conn)
    new_day = state.programme_day + 1
    update_state(
        conn,
        programme_day=new_day,
        last_calendar_date=today or state.last_calendar_date,
        suggestion_dismissed_date=None,
    )
    ensure_planned_sets(conn)
    ensure_active_capacity(conn, auto_replace=True)
    return new_day


def dismiss_day_suggestion(conn: sqlite3.Connection, today: str) -> None:
    update_state(conn, suggestion_dismissed_date=today)


def activate_set(conn: sqlite3.Connection, set_id: int) -> None:
    row = _programme_set(conn, set_id)
    if row["state"] == SET_ACTIVE:
        return
    if row["state"] != SET_PLANNED:
        raise ValueError("Solo se puede activar un set planificado")
    word_ids = _set_word_ids(conn, set_id)
    for word_id in word_ids:
        if _word_in_open_programme_set(conn, word_id, exclude_set_id=set_id):
            word = conn.execute("SELECT word FROM words WHERE id = ?", (word_id,)).fetchone()
            raise ValueError(f"«{word['word']}» ya está en otro set activo o planificado")
    state = get_state(conn)
    active_count = _active_programme_count(conn)
    if active_count >= state.max_active_sets:
        raise ValueError("Ya hay el máximo de sets activos")
    now = utc_now()
    conn.execute(
        """
        UPDATE word_sets
        SET state = ?, activated_at = ?, activated_programme_day = ?
        WHERE id = ?
        """,
        (SET_ACTIVE, now, state.programme_day, set_id),
    )
    for word_id in word_ids:
        stats = load_stats(conn, word_id)
        if stats.introduced_programme_day is None:
            stats.introduced_at = now
            stats.introduced_programme_day = state.programme_day
            save_stats(conn, stats)
        conn.execute("UPDATE words SET state = ? WHERE id = ?", (WORD_ACTIVE, word_id))


def retire_set(conn: sqlite3.Connection, set_id: int, *, replace: bool = True) -> None:
    row = _programme_set(conn, set_id)
    if row["state"] == SET_RETIRED:
        return
    if row["state"] not in {SET_ACTIVE, SET_PLANNED}:
        raise ValueError("Ese set no se puede retirar")
    state = get_state(conn)
    now = utc_now()
    conn.execute(
        """
        UPDATE word_sets
        SET state = ?, retired_at = ?, retired_programme_day = ?
        WHERE id = ?
        """,
        (SET_RETIRED, now, state.programme_day, set_id),
    )
    if row["state"] == SET_ACTIVE:
        for word_id in _set_word_ids(conn, set_id):
            if _word_in_open_programme_set(conn, word_id, exclude_set_id=set_id):
                continue
            stats = load_stats(conn, word_id)
            stats.retired_at = now
            stats.retired_programme_day = state.programme_day
            save_stats(conn, stats)
            conn.execute("UPDATE words SET state = ? WHERE id = ?", (WORD_RETIRED, word_id))
    if replace:
        ensure_planned_sets(conn)
        ensure_active_capacity(conn)


def set_is_eligible(conn: sqlite3.Connection, set_id: int) -> bool:
    row = conn.execute(
        "SELECT state, kind FROM word_sets WHERE id = ?",
        (set_id,),
    ).fetchone()
    if row is None or row["kind"] != KIND_PROGRAMME or row["state"] != SET_ACTIVE:
        return False
    state = get_state(conn)
    for word_id in _set_word_ids(conn, set_id):
        stats = load_stats(conn, word_id)
        if not retirement_eligible(
            stats.retirement_presentations,
            stats.introduced_programme_day,
            state.programme_day,
            state.retirement_exposure_target,
            state.retirement_min_days,
        ):
            return False
    return True


def eligible_set_ids(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        """
        SELECT id FROM word_sets
        WHERE kind = ? AND state = ?
        ORDER BY sort_order, id
        """,
        (KIND_PROGRAMME, SET_ACTIVE),
    ).fetchall()
    return [int(row["id"]) for row in rows if set_is_eligible(conn, int(row["id"]))]


def choose_next_set(conn: sqlite3.Connection, exclude_set_id: int | None = None) -> int | None:
    state = get_state(conn)
    rows = conn.execute(
        """
        SELECT id, sort_order FROM word_sets
        WHERE kind = ? AND state = ?
        ORDER BY sort_order, id
        """,
        (KIND_PROGRAMME, SET_ACTIVE),
    ).fetchall()
    if not rows:
        return None

    def sort_key(row: sqlite3.Row) -> tuple[int, int, int, int, int]:
        set_id = int(row["id"])
        return (
            1 if exclude_set_id is not None and set_id == exclude_set_id else 0,
            _session_count(conn, set_id, state.programme_day, SESSION_NORMAL),
            _session_count(conn, set_id, None, SESSION_NORMAL),
            int(row["sort_order"]),
            set_id,
        )

    return int(min(rows, key=sort_key)["id"])


def start_session(
    conn: sqlite3.Connection,
    set_id: int | None,
    session_type: str,
    *,
    counts_toward_retirement: bool | None = None,
) -> int:
    if session_type == SESSION_NORMAL:
        row = _programme_set(conn, set_id if set_id is not None else -1)
        if row["state"] != SET_ACTIVE:
            raise ValueError("El set del programa no está activo")
    state = get_state(conn)
    if counts_toward_retirement is None:
        counts_toward_retirement = session_type == SESSION_NORMAL
    cursor = conn.execute(
        """
        INSERT INTO sessions (
            set_id, started_at, programme_day, session_type, counts_toward_retirement
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (set_id, utc_now(), state.programme_day, session_type, int(counts_toward_retirement)),
    )
    return int(cursor.lastrowid)


def complete_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        "UPDATE sessions SET completed_at = ? WHERE id = ? AND completed_at IS NULL",
        (utc_now(), session_id),
    )
    session = conn.execute("SELECT set_id, session_type FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None or session["set_id"] is None:
        return
    if session["session_type"] == SESSION_NORMAL:
        return
    conn.execute(
        """
        UPDATE word_sets
        SET state = ?, retired_at = COALESCE(retired_at, ?)
        WHERE id = ? AND kind != ?
        """,
        (SET_RETIRED, utc_now(), int(session["set_id"]), KIND_PROGRAMME),
    )


def ordered_word_ids(conn: sqlite3.Connection, set_id: int, shuffle: bool | None = None) -> list[int]:
    rows = conn.execute(
        "SELECT word_id FROM set_words WHERE set_id = ? ORDER BY position",
        (set_id,),
    ).fetchall()
    word_ids = [int(row["word_id"]) for row in rows]
    if shuffle is None:
        shuffle = get_state(conn).shuffle_within_set
    if shuffle:
        random.shuffle(word_ids)
    return word_ids


def present_result(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    word_id: int,
    set_id: int | None,
    result: str,
    display_mode: str,
    case_mode: str,
) -> None:
    record_presentation(
        conn,
        session_id=session_id,
        word_id=word_id,
        set_id=set_id,
        result=result,
        display_mode=display_mode,
        case_mode=case_mode,
    )


def reinforcement_candidates(conn: sqlite3.Connection, limit: int | None = None) -> list[int]:
    state = get_state(conn)
    cap = limit if limit is not None else state.words_per_set
    rows = conn.execute(
        """
        SELECT s.word_id
        FROM word_stats s
        JOIN words w ON w.id = s.word_id
        WHERE w.enabled = 1 AND s.reinforcement_score >= ?
        ORDER BY s.reinforcement_score DESC, s.incorrect_count DESC, w.word
        LIMIT ?
        """,
        (REINFORCEMENT_THRESHOLD, cap),
    ).fetchall()
    return [int(row["word_id"]) for row in rows]


def start_reinforcement_session(conn: sqlite3.Connection) -> tuple[int, int] | None:
    word_ids = reinforcement_candidates(conn)
    if not word_ids:
        return None
    set_id = _create_ephemeral_set(conn, "Refuerzo", word_ids, KIND_REINFORCEMENT)
    session_id = start_session(conn, set_id, SESSION_REINFORCEMENT, counts_toward_retirement=False)
    return session_id, set_id


def start_manual_word_session(conn: sqlite3.Connection, word_ids: list[int]) -> tuple[int, int]:
    if not word_ids:
        raise ValueError("Elige al menos una palabra")
    unique: list[int] = []
    for word_id in word_ids:
        if word_id not in unique:
            unique.append(word_id)
    set_id = _create_ephemeral_set(conn, "Presentación libre", unique, KIND_MANUAL)
    state = get_state(conn)
    session_id = start_session(
        conn,
        set_id,
        SESSION_MANUAL,
        counts_toward_retirement=state.manual_counts_toward_retirement,
    )
    return session_id, set_id


def start_manual_set_session(conn: sqlite3.Connection, set_id: int) -> int:
    row = conn.execute("SELECT kind FROM word_sets WHERE id = ?", (set_id,)).fetchone()
    if row is None:
        raise KeyError(set_id)
    state = get_state(conn)
    return start_session(
        conn,
        set_id,
        SESSION_MANUAL,
        counts_toward_retirement=state.manual_counts_toward_retirement,
    )


def create_programme_set(conn: sqlite3.Connection, name: str, word_ids: list[int]) -> int:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("El set necesita un nombre")
    state = get_state(conn)
    if len(word_ids) != state.words_per_set:
        raise ValueError(f"Un set necesita {state.words_per_set} palabras")
    if len(set(word_ids)) != len(word_ids):
        raise ValueError("Hay palabras repetidas")
    for word_id in word_ids:
        conn.execute(
            "UPDATE words SET state = 'AVAILABLE' WHERE id = ? AND state = 'RETIRED'",
            (word_id,),
        )
    for word_id in word_ids:
        if _word_in_open_programme_set(conn, word_id):
            word = conn.execute("SELECT word FROM words WHERE id = ?", (word_id,)).fetchone()
            raise ValueError(f"«{word['word']}» ya pertenece a un set abierto")
    return _insert_set(conn, cleaned, None, word_ids, KIND_PROGRAMME, SET_PLANNED)


def rename_set(conn: sqlite3.Connection, set_id: int, name: str) -> None:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("El set necesita un nombre")
    found = conn.execute("SELECT id FROM word_sets WHERE id = ?", (set_id,)).fetchone()
    if found is None:
        raise KeyError(set_id)
    conn.execute("UPDATE word_sets SET name = ? WHERE id = ?", (cleaned, set_id))


def replace_planned_words(conn: sqlite3.Connection, set_id: int, word_ids: list[int]) -> None:
    row = _programme_set(conn, set_id)
    if row["state"] != SET_PLANNED:
        raise ValueError("Solo se editan las palabras de un set planificado")
    state = get_state(conn)
    if len(word_ids) != state.words_per_set or len(set(word_ids)) != len(word_ids):
        raise ValueError(f"Elige {state.words_per_set} palabras distintas")
    for word_id in word_ids:
        if _word_in_open_programme_set(conn, word_id, exclude_set_id=set_id):
            word = conn.execute("SELECT word FROM words WHERE id = ?", (word_id,)).fetchone()
            raise ValueError(f"«{word['word']}» ya pertenece a otro set abierto")
    conn.execute("DELETE FROM set_words WHERE set_id = ?", (set_id,))
    for position, word_id in enumerate(word_ids, start=1):
        conn.execute(
            "INSERT INTO set_words (set_id, word_id, position) VALUES (?, ?, ?)",
            (set_id, word_id, position),
        )


def move_planned_set(conn: sqlite3.Connection, set_id: int, direction: int) -> None:
    row = _programme_set(conn, set_id)
    if row["state"] != SET_PLANNED:
        raise ValueError("Solo se reordenan sets planificados")
    if direction not in {-1, 1}:
        raise ValueError("Dirección no válida")
    neighbors = conn.execute(
        """
        SELECT id, sort_order FROM word_sets
        WHERE kind = ? AND state = ?
        ORDER BY sort_order, id
        """,
        (KIND_PROGRAMME, SET_PLANNED),
    ).fetchall()
    ids = [int(item["id"]) for item in neighbors]
    if set_id not in ids:
        return
    index = ids.index(set_id)
    swap_index = index + direction
    if swap_index < 0 or swap_index >= len(ids):
        return
    current_order = int(row["sort_order"])
    other = neighbors[swap_index]
    conn.execute("UPDATE word_sets SET sort_order = ? WHERE id = ?", (int(other["sort_order"]), set_id))
    conn.execute("UPDATE word_sets SET sort_order = ? WHERE id = ?", (current_order, int(other["id"])))


def reactivate_word(conn: sqlite3.Connection, word_id: int) -> None:
    """Adult override. Does not put the word back into a set by itself."""
    row = conn.execute("SELECT state FROM words WHERE id = ?", (word_id,)).fetchone()
    if row is None:
        raise KeyError(word_id)
    if _word_in_open_programme_set(conn, word_id):
        raise ValueError("La palabra ya está en un set abierto")
    conn.execute(
        "UPDATE words SET state = 'AVAILABLE' WHERE id = ? AND state = ?",
        (word_id, WORD_RETIRED),
    )


def list_sets(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT id, name, category, state, kind, sort_order,
                   activated_programme_day, retired_programme_day
            FROM word_sets
            WHERE kind = ?
            ORDER BY
                CASE state WHEN 'ACTIVE' THEN 0 WHEN 'PLANNED' THEN 1 ELSE 2 END,
                sort_order, id
            """,
            (KIND_PROGRAMME,),
        ).fetchall()
    )


def set_word_labels(conn: sqlite3.Connection, set_id: int) -> list[str]:
    rows = conn.execute(
        """
        SELECT w.word FROM set_words sw
        JOIN words w ON w.id = sw.word_id
        WHERE sw.set_id = ?
        ORDER BY sw.position
        """,
        (set_id,),
    ).fetchall()
    return [str(row["word"]) for row in rows]


def session_count_today(conn: sqlite3.Connection, set_id: int) -> int:
    state = get_state(conn)
    return _session_count(conn, set_id, state.programme_day, SESSION_NORMAL)


def session_count_total(conn: sqlite3.Connection, set_id: int) -> int:
    return _session_count(conn, set_id, None, SESSION_NORMAL)


def _plan_category_sets(conn: sqlite3.Connection, words_per_set: int) -> int:
    rows = conn.execute(
        """
        SELECT w.id, w.category
        FROM words w
        WHERE w.source = ? AND w.enabled = 1 AND NOT EXISTS (
            SELECT 1 FROM words other
            JOIN set_words sw ON sw.word_id = other.id
            JOIN word_sets ws ON ws.id = sw.set_id
            WHERE other.word_key = w.word_key AND ws.kind = ?
        )
        ORDER BY w.id
        """,
        (SOURCE_MIS_PALABRAS, KIND_PROGRAMME),
    ).fetchall()
    grouped: dict[str, list[int]] = {}
    for row in rows:
        grouped.setdefault(str(row["category"] or "otros"), []).append(int(row["id"]))
    created = 0
    for category in sorted(grouped, key=category_sort_key):
        chunks = _chunks(grouped[category], words_per_set)
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            label = display_category(category)
            name = label if total == 1 else f"{label} {index}"
            _insert_set(conn, name, category, chunk, KIND_PROGRAMME, SET_PLANNED)
            created += 1
    return created


def _plan_frequency_sets(conn: sqlite3.Connection, words_per_set: int) -> int:
    rows = conn.execute(
        """
        SELECT w.id, w.word_key, w.rank
        FROM words w
        WHERE w.source = ? AND w.enabled = 1 AND NOT EXISTS (
            SELECT 1 FROM words other
            JOIN set_words sw ON sw.word_id = other.id
            JOIN word_sets ws ON ws.id = sw.set_id
            WHERE other.word_key = w.word_key AND ws.kind = ?
        )
        """,
        (SOURCE_FRECUENCIA, KIND_PROGRAMME),
    ).fetchall()
    content: list[sqlite3.Row] = []
    function_rows: list[sqlite3.Row] = []
    for row in rows:
        if str(row["word_key"]) in FUNCTION_WORD_SET:
            function_rows.append(row)
        else:
            content.append(row)
    content.sort(key=lambda row: (row["rank"] is None, row["rank"] if row["rank"] is not None else 0, row["id"]))
    function_rows.sort(key=lambda row: (row["rank"] is None, row["rank"] if row["rank"] is not None else 0, row["id"]))
    created = 0
    created += _plan_named_chunks(conn, [int(row["id"]) for row in content], words_per_set, "Frecuencia", "frecuencia")
    created += _plan_named_chunks(
        conn, [int(row["id"]) for row in function_rows], words_per_set, "Función", "funcion"
    )
    return created


def _plan_named_chunks(
    conn: sqlite3.Connection,
    word_ids: list[int],
    words_per_set: int,
    prefix: str,
    category: str,
) -> int:
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM word_sets WHERE kind = ? AND category = ?",
        (KIND_PROGRAMME, category),
    ).fetchone()
    start = int(existing["n"])
    created = 0
    for offset, chunk in enumerate(_chunks(word_ids, words_per_set), start=1):
        _insert_set(conn, f"{prefix} {start + offset}", category, chunk, KIND_PROGRAMME, SET_PLANNED)
        created += 1
    return created


def _chunks(word_ids: list[int], size: int) -> list[list[int]]:
    return [word_ids[index : index + size] for index in range(0, len(word_ids) - size + 1, size)]


def _insert_set(
    conn: sqlite3.Connection,
    name: str,
    category: str | None,
    word_ids: list[int],
    kind: str,
    state: str,
) -> int:
    current = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS n FROM word_sets").fetchone()
    sort_order = int(current["n"]) + 1
    cursor = conn.execute(
        """
        INSERT INTO word_sets (name, category, state, kind, sort_order, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (name, category, state, kind, sort_order, utc_now()),
    )
    set_id = int(cursor.lastrowid)
    for position, word_id in enumerate(word_ids, start=1):
        conn.execute(
            "INSERT INTO set_words (set_id, word_id, position) VALUES (?, ?, ?)",
            (set_id, word_id, position),
        )
    return set_id


def _create_ephemeral_set(conn: sqlite3.Connection, prefix: str, word_ids: list[int], kind: str) -> int:
    count = conn.execute("SELECT COUNT(*) AS n FROM word_sets WHERE kind = ?", (kind,)).fetchone()
    name = f"{prefix} {int(count['n']) + 1}"
    return _insert_set(conn, name, None, word_ids, kind, SET_ACTIVE)


def _active_programme_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM word_sets WHERE kind = ? AND state = ?",
        (KIND_PROGRAMME, SET_ACTIVE),
    ).fetchone()
    return int(row["n"])


def _next_planned_set_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM word_sets
        WHERE kind = ? AND state = ?
        ORDER BY sort_order, id
        LIMIT 1
        """,
        (KIND_PROGRAMME, SET_PLANNED),
    ).fetchone()
    if row is None:
        return None
    return int(row["id"])


def _set_word_ids(conn: sqlite3.Connection, set_id: int) -> list[int]:
    rows = conn.execute(
        "SELECT word_id FROM set_words WHERE set_id = ? ORDER BY position",
        (set_id,),
    ).fetchall()
    return [int(row["word_id"]) for row in rows]


def _programme_set(conn: sqlite3.Connection, set_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM word_sets WHERE id = ? AND kind = ?",
        (set_id, KIND_PROGRAMME),
    ).fetchone()
    if row is None:
        raise KeyError(set_id)
    return row


def _word_in_open_programme_set(
    conn: sqlite3.Connection, word_id: int, exclude_set_id: int | None = None
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM set_words sw
        JOIN word_sets ws ON ws.id = sw.set_id
        WHERE sw.word_id = ? AND ws.kind = ? AND ws.state IN (?, ?)
          AND (? IS NULL OR ws.id != ?)
        LIMIT 1
        """,
        (word_id, KIND_PROGRAMME, SET_PLANNED, SET_ACTIVE, exclude_set_id, exclude_set_id),
    ).fetchone()
    return row is not None


def _session_count(
    conn: sqlite3.Connection, set_id: int, programme_day: int | None, session_type: str
) -> int:
    if programme_day is None:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM sessions
            WHERE set_id = ? AND session_type = ?
              AND id IN (SELECT session_id FROM presentations)
            """,
            (set_id, session_type),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM sessions
            WHERE set_id = ? AND session_type = ? AND programme_day = ?
              AND id IN (SELECT session_id FROM presentations)
            """,
            (set_id, session_type, programme_day),
        ).fetchone()
    return int(row["n"])
