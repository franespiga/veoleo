"""Writing stays on the same sets and never changes reading counters."""

from __future__ import annotations

import os
from pathlib import Path

from src.database import connect, initialize_schema
from src.display import apply_case
from src.doman_scheduler import choose_next_set, ordered_word_ids
from src.models import RESET_CONFIRMATION
from src.writing import attempt_marks, record_writing_attempt, start_writing_session


def test_attempt_marks_flag_mismatched_letters() -> None:
    sol = attempt_marks("sol", "sal")
    assert [mark["wrong"] for mark in sol] == [False, True, False]
    mama = attempt_marks("mamá", "mama")
    assert [mark["wrong"] for mark in mama] == [False, False, False, True]
    extra = attempt_marks("sol", "soll")
    assert [mark["wrong"] for mark in extra] == [False, False, False, True]
    exact = attempt_marks("mamá", "mamá")
    assert any(mark["wrong"] for mark in exact) is False


def test_schema_v1_gains_writing_tables_without_losing_reading(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    conn = connect(path)
    initialize_schema(conn)
    conn.execute("DROP TABLE writing_presentations")
    conn.execute("DROP TABLE writing_word_stats")
    conn.execute("DROP TABLE writing_sessions")
    conn.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")
    conn.execute("UPDATE programme_state SET programme_day = 4 WHERE id = 1")
    conn.execute(
        """
        INSERT INTO words (word, word_key, source, enabled, state, created_at)
        VALUES ('sol', 'sol', 'mis_palabras', 1, 'ACTIVE', '2026-01-01T00:00:00')
        """
    )
    word_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        """
        INSERT INTO sessions (started_at, programme_day, session_type, counts_toward_retirement)
        VALUES ('2026-01-01T00:00:00', 4, 'normal', 1)
        """
    )
    session_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.execute(
        """
        INSERT INTO presentations (
            session_id, word_id, timestamp, programme_day, display_mode, case_mode, result
        ) VALUES (?, ?, '2026-01-01T00:00:00', 4, 'doman_red', 'minusculas', 'exposure')
        """,
        (session_id, word_id),
    )
    initialize_schema(conn)
    version = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()[0]
    day = conn.execute("SELECT programme_day FROM programme_state WHERE id = 1").fetchone()[0]
    presentations = conn.execute("SELECT COUNT(*) AS n FROM presentations").fetchone()["n"]
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert version == "2"
    assert day == 4
    assert presentations == 1
    assert "writing_sessions" in tables
    assert "writing_presentations" in tables
    assert "writing_word_stats" in tables


def test_writing_attempt_does_not_change_reading_stats(manager) -> None:
    with manager.transaction() as conn:
        set_id = choose_next_set(conn)
        assert set_id is not None
        session_id = start_writing_session(conn, set_id)
        word_id = ordered_word_ids(conn, set_id, shuffle=False)[0]
        surface = str(conn.execute("SELECT word FROM words WHERE id = ?", (word_id,)).fetchone()["word"])
        shown = apply_case(surface, "minusculas")
        record_writing_attempt(
            conn,
            session_id=session_id,
            word_id=word_id,
            set_id=set_id,
            result="incorrect",
            attempt=shown + "x",
            complete=False,
        )
        record_writing_attempt(
            conn,
            session_id=session_id,
            word_id=word_id,
            set_id=set_id,
            result="correct",
            attempt=shown,
            complete=False,
        )
        reading = conn.execute("SELECT COUNT(*) AS n FROM presentations").fetchone()["n"]
        retirement = conn.execute(
            "SELECT COALESCE(SUM(retirement_presentations), 0) AS n FROM word_stats"
        ).fetchone()["n"]
        evaluated = conn.execute(
            """
            SELECT COALESCE(SUM(correct_count + incorrect_count + neutral_exposures), 0) AS n
            FROM word_stats
            """
        ).fetchone()["n"]
        writing = conn.execute(
            "SELECT times_presented, correct_count, incorrect_count FROM writing_word_stats WHERE word_id = ?",
            (word_id,),
        ).fetchone()
        state = conn.execute("SELECT state FROM words WHERE id = ?", (word_id,)).fetchone()["state"]
    assert reading == 0
    assert int(retirement) == 0
    assert int(evaluated) == 0
    assert int(writing["times_presented"]) == 2
    assert int(writing["correct_count"]) == 1
    assert int(writing["incorrect_count"]) == 1
    assert state == "ACTIVE"

    manager.reset_active(RESET_CONFIRMATION)
    with manager.transaction() as conn:
        left = conn.execute("SELECT COUNT(*) AS n FROM writing_presentations").fetchone()["n"]
    assert left == 0


def test_writing_api_keeps_reading_accuracy_and_serves_both_apps(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LECTURA_DATA_DIR", str(tmp_path / "data"))
    os.environ["LECTURA_DATA_DIR"] = str(tmp_path / "data")
    from fastapi.testclient import TestClient

    from app import app

    with TestClient(app) as client:
        for path in ("/", "/leer", "/escribir"):
            page = client.get(path)
            assert page.status_code == 200
            assert "Lectura" in page.text
        script = client.get("/static/app.js")
        assert "¿Qué practicamos?" in script.text
        assert "#0b1f4b" in client.get("/static/styles.css").text

        started = client.post("/api/writing/sessions", json={"kind": "next"})
        assert started.status_code == 200, started.text
        session = started.json()
        word = session["words"][0]
        rejected = client.post(
            f"/api/writing/sessions/{session['session_id']}/attempt",
            json={
                "word_id": word["id"],
                "set_id": session["set_id"],
                "result": "correct",
                "attempt": word["shown"] + "x",
                "complete": False,
            },
        )
        assert rejected.status_code == 400
        wrong = client.post(
            f"/api/writing/sessions/{session['session_id']}/attempt",
            json={
                "word_id": word["id"],
                "set_id": session["set_id"],
                "result": "incorrect",
                "attempt": word["shown"] + "x",
                "complete": False,
            },
        )
        assert wrong.status_code == 200, wrong.text
        right = client.post(
            f"/api/writing/sessions/{session['session_id']}/attempt",
            json={
                "word_id": word["id"],
                "set_id": session["set_id"],
                "result": "correct",
                "attempt": word["shown"],
                "complete": False,
            },
        )
        assert right.status_code == 200, right.text

        reading = client.get("/api/progress")
        summary = reading.json()["summary"]
        assert summary["neutral_exposures"] == 0
        assert summary["correct_readings"] == 0
        assert summary["incorrect_readings"] == 0
        written = client.get("/api/writing/progress")
        body = written.json()
        assert body["attempts"] == 2
        assert body["correct_count"] == 1
        assert body["incorrect_count"] == 1
