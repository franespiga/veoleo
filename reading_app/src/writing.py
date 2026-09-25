"""Writing practice on the same programme sets, stored apart from reading."""

from __future__ import annotations

import sqlite3

from src.database import get_state, utc_now
from src.display import apply_case
from src.doman_scheduler import ordered_word_ids
from src.models import KIND_PROGRAMME, RESULT_CORRECT, RESULT_INCORRECT, SESSION_NORMAL, SET_ACTIVE
from src.statistics import format_accuracy

WRITING_RESULTS = (RESULT_CORRECT, RESULT_INCORRECT)


def attempt_marks(expected: str, attempt: str) -> list[dict[str, object]]:
    """Mark each typed character that does not match the shown word.

    Comparison is by Unicode code point, so ``mamá`` and ``mama`` differ on
    the last letter. Extra characters past the target are marked too.
    """
    expected_chars = list(expected)
    marks: list[dict[str, object]] = []
    for index, char in enumerate(attempt):
        wrong = index >= len(expected_chars) or char != expected_chars[index]
        marks.append({"char": char, "wrong": wrong})
    return marks


def choose_next_writing_set(conn: sqlite3.Connection, exclude_set_id: int | None = None) -> int | None:
    """Pick the next active programme set using writing sessions, not reading ones."""
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
            _writing_session_count(conn, set_id, state.programme_day),
            _writing_session_count(conn, set_id, None),
            int(row["sort_order"]),
            set_id,
        )

    return int(min(rows, key=sort_key)["id"])


def start_writing_session(conn: sqlite3.Connection, set_id: int) -> int:
    row = conn.execute(
        "SELECT state, kind FROM word_sets WHERE id = ?",
        (set_id,),
    ).fetchone()
    if row is None or row["kind"] != KIND_PROGRAMME or row["state"] != SET_ACTIVE:
        raise ValueError("El set del programa no está activo")
    state = get_state(conn)
    cursor = conn.execute(
        """
        INSERT INTO writing_sessions (set_id, started_at, programme_day, session_type)
        VALUES (?, ?, ?, ?)
        """,
        (set_id, utc_now(), state.programme_day, SESSION_NORMAL),
    )
    return int(cursor.lastrowid)


def writing_session_payload(conn: sqlite3.Connection, session_id: int, set_id: int) -> dict:
    state = get_state(conn)
    word_ids = ordered_word_ids(conn, set_id, shuffle=bool(state.shuffle_within_set))
    if not word_ids:
        raise ValueError("Ese set no tiene palabras.")
    words = []
    for word_id in word_ids:
        row = conn.execute("SELECT word FROM words WHERE id = ?", (word_id,)).fetchone()
        surface = str(row["word"])
        words.append({"id": word_id, "word": surface, "shown": apply_case(surface, state.case_mode)})
    name = conn.execute("SELECT name FROM word_sets WHERE id = ?", (set_id,)).fetchone()
    return {
        "session_id": session_id,
        "set_id": set_id,
        "set_name": str(name["name"]) if name else "",
        "session_type": SESSION_NORMAL,
        "words": words,
        "case_mode": state.case_mode,
    }


def record_writing_attempt(
    conn: sqlite3.Connection,
    *,
    session_id: int,
    word_id: int,
    set_id: int,
    result: str,
    attempt: str,
    complete: bool,
) -> None:
    """Store one writing attempt. Reading counters and retirement stay untouched."""
    if result not in WRITING_RESULTS:
        raise ValueError("Resultado de escritura no válido")
    session = conn.execute("SELECT * FROM writing_sessions WHERE id = ?", (session_id,)).fetchone()
    if session is None:
        raise KeyError("No existe esa sesión de escritura")
    if session["completed_at"] is not None:
        raise ValueError("Esa sesión de escritura ya terminó")
    if int(session["set_id"]) != set_id:
        raise ValueError("El set no corresponde a la sesión")
    member = conn.execute(
        "SELECT 1 FROM set_words WHERE set_id = ? AND word_id = ?",
        (set_id, word_id),
    ).fetchone()
    if member is None:
        raise ValueError("Esa palabra no está en el set")
    word = conn.execute("SELECT word FROM words WHERE id = ?", (word_id,)).fetchone()
    if word is None:
        raise KeyError("No existe esa palabra")
    state = get_state(conn)
    expected = apply_case(str(word["word"]), state.case_mode)
    if result == RESULT_CORRECT and attempt != expected:
        raise ValueError("La palabra escrita no coincide")
    if result == RESULT_INCORRECT and attempt == expected:
        raise ValueError("La palabra escrita coincide")
    if complete and result != RESULT_CORRECT:
        raise ValueError("La sesión solo se cierra con la palabra correcta")
    timestamp = utc_now()
    conn.execute(
        """
        INSERT INTO writing_presentations (
            session_id, word_id, set_id, timestamp, programme_day, case_mode, result, attempt
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (session_id, word_id, set_id, timestamp, state.programme_day, state.case_mode, result, attempt),
    )
    _bump_writing_stats(conn, word_id, result, timestamp)
    if complete:
        conn.execute(
            "UPDATE writing_sessions SET completed_at = ? WHERE id = ? AND completed_at IS NULL",
            (timestamp, session_id),
        )


def writing_progress(conn: sqlite3.Connection) -> dict:
    totals = conn.execute(
        """
        SELECT
            COUNT(*) AS attempts,
            COALESCE(SUM(CASE WHEN result = 'correct' THEN 1 ELSE 0 END), 0) AS correct_count,
            COALESCE(SUM(CASE WHEN result = 'incorrect' THEN 1 ELSE 0 END), 0) AS incorrect_count
        FROM writing_presentations
        """
    ).fetchone()
    correct = int(totals["correct_count"])
    incorrect = int(totals["incorrect_count"])
    rows = conn.execute(
        """
        SELECT w.word, s.times_presented, s.correct_count, s.incorrect_count, s.last_presented
        FROM writing_word_stats s
        JOIN words w ON w.id = s.word_id
        ORDER BY s.last_presented DESC, w.word
        """
    ).fetchall()
    return {
        "attempts": int(totals["attempts"]),
        "correct_count": correct,
        "incorrect_count": incorrect,
        "accuracy": format_accuracy(correct, incorrect),
        "words": [
            {
                "word": row["word"],
                "times_presented": int(row["times_presented"]),
                "correct_count": int(row["correct_count"]),
                "incorrect_count": int(row["incorrect_count"]),
                "accuracy": format_accuracy(int(row["correct_count"]), int(row["incorrect_count"])),
                "last_presented": row["last_presented"],
            }
            for row in rows
        ],
    }


def _bump_writing_stats(conn: sqlite3.Connection, word_id: int, result: str, timestamp: str) -> None:
    row = conn.execute("SELECT * FROM writing_word_stats WHERE word_id = ?", (word_id,)).fetchone()
    correct_delta = 1 if result == RESULT_CORRECT else 0
    incorrect_delta = 1 if result == RESULT_INCORRECT else 0
    if row is None:
        conn.execute(
            """
            INSERT INTO writing_word_stats (
                word_id, times_presented, correct_count, incorrect_count, last_presented, last_correct
            ) VALUES (?, 1, ?, ?, ?, ?)
            """,
            (word_id, correct_delta, incorrect_delta, timestamp, timestamp if correct_delta else None),
        )
        return
    conn.execute(
        """
        UPDATE writing_word_stats
        SET times_presented = ?, correct_count = ?, incorrect_count = ?,
            last_presented = ?, last_correct = ?
        WHERE word_id = ?
        """,
        (
            int(row["times_presented"]) + 1,
            int(row["correct_count"]) + correct_delta,
            int(row["incorrect_count"]) + incorrect_delta,
            timestamp,
            timestamp if correct_delta else row["last_correct"],
            word_id,
        ),
    )


def _writing_session_count(conn: sqlite3.Connection, set_id: int, programme_day: int | None) -> int:
    if programme_day is None:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM writing_sessions
            WHERE set_id = ? AND session_type = ?
              AND id IN (SELECT session_id FROM writing_presentations)
            """,
            (set_id, SESSION_NORMAL),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM writing_sessions
            WHERE set_id = ? AND session_type = ? AND programme_day = ?
              AND id IN (SELECT session_id FROM writing_presentations)
            """,
            (set_id, SESSION_NORMAL, programme_day),
        ).fetchone()
    return int(row["n"])
