import sqlite3

from src.database import get_state, load_stats
from src.database_manager import DatabaseManager
from src.doman_scheduler import (
    advance_programme_day,
    choose_next_set,
    create_programme_set,
    eligible_set_ids,
    list_sets,
    ordered_word_ids,
    present_result,
    reinforcement_candidates,
    session_count_today,
    set_is_eligible,
    set_word_labels,
    start_manual_word_session,
    start_session,
    target_active_sets,
    retire_set,
)
from src.models import RESULT_CORRECT, RESULT_EXPOSURE, RESULT_INCORRECT, SESSION_NORMAL, WordStats
from src.statistics import accuracy, apply_result, evaluated_attempts, format_accuracy


def _active_sets(manager: DatabaseManager) -> list[sqlite3.Row]:
    with manager.transaction() as conn:
        return [row for row in list_sets(conn) if row["state"] == "ACTIVE"]


def _set_named(manager: DatabaseManager, name: str) -> sqlite3.Row:
    with manager.transaction() as conn:
        for row in list_sets(conn):
            if row["name"] == name:
                return row
    raise AssertionError(name)


def _present_words(manager: DatabaseManager, set_id: int, times: int, result: str = RESULT_EXPOSURE) -> None:
    with manager.transaction() as conn:
        session_id = start_session(conn, set_id, SESSION_NORMAL)
        word_ids = ordered_word_ids(conn, set_id, shuffle=False)
        state = get_state(conn)
        for _ in range(times):
            for word_id in word_ids:
                present_result(
                    conn,
                    session_id=session_id,
                    word_id=word_id,
                    set_id=set_id,
                    result=result,
                    display_mode=state.display_mode,
                    case_mode=state.case_mode,
                )


def test_target_grows_then_stops_at_the_maximum() -> None:
    assert target_active_sets(1, 5) == 1
    assert target_active_sets(2, 5) == 2
    assert target_active_sets(4, 5) == 4
    assert target_active_sets(5, 5) == 5
    assert target_active_sets(12, 5) == 5


def test_day_one_activates_one_thematic_family_set(manager: DatabaseManager) -> None:
    active = _active_sets(manager)
    assert len(active) == 1
    assert active[0]["name"] == "Familia"
    with manager.transaction() as conn:
        assert get_state(conn).programme_day == 1
        assert set_word_labels(conn, int(active[0]["id"])) == ["mamá", "papá", "niño", "tío", "bebé"]
        categories = conn.execute(
            """
            SELECT DISTINCT w.category
            FROM set_words sw JOIN words w ON w.id = sw.word_id
            WHERE sw.set_id = ?
            """,
            (int(active[0]["id"]),),
        ).fetchall()
        assert [row["category"] for row in categories] == ["familia"]
        disabled = conn.execute("SELECT state FROM words WHERE word = 'secreto'").fetchone()
        assert disabled["state"] == "AVAILABLE"
        assert conn.execute(
            "SELECT 1 FROM set_words sw JOIN words w ON w.id = sw.word_id WHERE w.word = 'secreto'"
        ).fetchone() is None


def test_sets_do_not_mix_categories(manager: DatabaseManager) -> None:
    with manager.transaction() as conn:
        rows = conn.execute(
            """
            SELECT sw.set_id, COUNT(DISTINCT w.category) AS categories
            FROM set_words sw
            JOIN words w ON w.id = sw.word_id
            JOIN word_sets ws ON ws.id = sw.set_id
            WHERE ws.kind = 'programme'
            GROUP BY sw.set_id
            """
        ).fetchall()
    assert rows
    assert all(int(row["categories"]) == 1 for row in rows)


def test_day_two_and_cap(manager: DatabaseManager) -> None:
    with manager.transaction() as conn:
        advance_programme_day(conn)
        assert get_state(conn).programme_day == 2
    assert len(_active_sets(manager)) == 2
    for _ in range(8):
        with manager.transaction() as conn:
            advance_programme_day(conn)
            state = get_state(conn)
            active = conn.execute(
                "SELECT COUNT(*) AS n FROM word_sets WHERE kind = 'programme' AND state = 'ACTIVE'"
            ).fetchone()
            assert int(active["n"]) <= state.max_active_sets
    assert len(_active_sets(manager)) == 5
    with manager.transaction() as conn:
        planned = [row for row in list_sets(conn) if row["state"] == "PLANNED"]
        assert planned
        try:
            from src.doman_scheduler import activate_set

            activate_set(conn, int(planned[0]["id"]))
            raise AssertionError("no debía activar por encima del máximo")
        except ValueError:
            pass


def test_retiring_a_set_brings_in_the_next_and_keeps_history(manager: DatabaseManager) -> None:
    familia = _set_named(manager, "Familia")
    _present_words(manager, int(familia["id"]), 1, RESULT_EXPOSURE)
    for _ in range(4):
        with manager.transaction() as conn:
            advance_programme_day(conn)
    assert len(_active_sets(manager)) == 5
    with manager.transaction() as conn:
        before = conn.execute("SELECT COUNT(*) AS n FROM presentations").fetchone()
        retire_set(conn, int(familia["id"]))
        after = conn.execute("SELECT COUNT(*) AS n FROM presentations").fetchone()
        retired = conn.execute("SELECT state FROM word_sets WHERE id = ?", (int(familia["id"]),)).fetchone()
        word = conn.execute("SELECT state FROM words WHERE word = 'mamá' AND source = 'mis_palabras'").fetchone()
        stats = conn.execute(
            """
            SELECT times_presented FROM word_stats s
            JOIN words w ON w.id = s.word_id
            WHERE w.word = 'mamá'
            """
        ).fetchone()
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM word_sets WHERE kind = 'programme' AND state = 'ACTIVE'"
        ).fetchone()
    assert int(before["n"]) > 0
    assert int(after["n"]) == int(before["n"])
    assert retired["state"] == "RETIRED"
    assert word["state"] == "RETIRED"
    assert int(stats["times_presented"]) == 1
    assert int(active["n"]) == 5


def test_retirement_requires_exposures_and_days(manager: DatabaseManager) -> None:
    familia = _set_named(manager, "Familia")
    _present_words(manager, int(familia["id"]), 15, RESULT_EXPOSURE)
    with manager.transaction() as conn:
        assert get_state(conn).retirement_exposure_target == 15
        assert get_state(conn).retirement_min_days == 5
        assert set_is_eligible(conn, int(familia["id"])) is False
        for _ in range(4):
            advance_programme_day(conn)
        assert get_state(conn).programme_day == 5
        assert set_is_eligible(conn, int(familia["id"])) is True
        assert int(familia["id"]) in eligible_set_ids(conn)


def test_auto_retire_replaces_on_day_advance(manager: DatabaseManager) -> None:
    manager.update_settings(max_active_sets=2, retirement_exposure_target=1, retirement_min_days=1)
    with manager.transaction() as conn:
        advance_programme_day(conn)
    familia = _set_named(manager, "Familia")
    _present_words(manager, int(familia["id"]), 1)
    manager.update_settings(auto_retire=True)
    with manager.transaction() as conn:
        assert set_is_eligible(conn, int(familia["id"])) is True
        advance_programme_day(conn)
        state = conn.execute("SELECT state FROM word_sets WHERE name = 'Familia'").fetchone()
        active_names = [
            row["name"]
            for row in conn.execute(
                "SELECT name FROM word_sets WHERE kind = 'programme' AND state = 'ACTIVE' ORDER BY sort_order"
            )
        ]
        kept = conn.execute(
            """
            SELECT COUNT(*) AS n FROM presentations p
            JOIN words w ON w.id = p.word_id
            WHERE w.word = 'mamá'
            """
        ).fetchone()
    assert state["state"] == "RETIRED"
    assert active_names == ["Animales", "Cuerpo"]
    assert int(kept["n"]) == 1


def test_frequency_sets_postpone_function_words(manager: DatabaseManager) -> None:
    manager.update_settings(vocabulary_source="frecuencia")
    with manager.transaction() as conn:
        content = conn.execute("SELECT id FROM word_sets WHERE name = 'Frecuencia 1'").fetchone()
        function = conn.execute("SELECT id FROM word_sets WHERE name = 'Función 1'").fetchone()
        assert set(set_word_labels(conn, int(content["id"]))) == {"piedra", "nube", "viento", "fuego", "arena"}
        assert set(set_word_labels(conn, int(function["id"]))) == {"de", "que", "el", "la", "y"}
        active = {label for row in _active_rows(conn) for label in set_word_labels(conn, int(row["id"]))}
    assert "de" not in active


def _active_rows(conn):
    return [row for row in list_sets(conn) if row["state"] == "ACTIVE"]


def test_duplicate_open_word_is_rejected(manager: DatabaseManager) -> None:
    with manager.transaction() as conn:
        active_word = conn.execute(
            """
            SELECT sw.word_id FROM set_words sw
            JOIN word_sets ws ON ws.id = sw.set_id
            WHERE ws.state = 'ACTIVE'
            LIMIT 1
            """
        ).fetchone()
        free = [
            int(row["id"])
            for row in conn.execute(
                """
                SELECT w.id FROM words w
                WHERE w.enabled = 1 AND w.word != 'mamá' AND NOT EXISTS (
                    SELECT 1 FROM set_words sw
                    JOIN word_sets ws ON ws.id = sw.set_id
                    WHERE sw.word_id = w.id AND ws.kind = 'programme' AND ws.state IN ('PLANNED', 'ACTIVE')
                )
                LIMIT 4
                """
            )
        ]
        try:
            create_programme_set(conn, "Mezcla", [int(active_word["word_id"]), *free])
            raise AssertionError("debía rechazar la palabra ya usada")
        except ValueError:
            pass


def test_presentation_accounting_and_skip(manager: DatabaseManager) -> None:
    pure = WordStats(word_id=1)
    for result in (
        RESULT_EXPOSURE,
        RESULT_EXPOSURE,
        RESULT_CORRECT,
        RESULT_CORRECT,
        RESULT_CORRECT,
        RESULT_INCORRECT,
    ):
        apply_result(pure, result, True, "2026-09-21T10:00:00")
    assert pure.times_presented == 6
    assert pure.neutral_exposures == 2
    assert pure.correct_count == 3
    assert pure.incorrect_count == 1
    assert evaluated_attempts(pure.correct_count, pure.incorrect_count) == 4
    assert accuracy(pure.correct_count, pure.incorrect_count) == 0.75
    assert format_accuracy(0, 0) == "Sin evaluar"

    skipped = WordStats(word_id=2)
    apply_result(skipped, RESULT_EXPOSURE, True, "2026-09-21T10:00:00")
    assert skipped.correct_count == 0
    assert skipped.incorrect_count == 0
    assert skipped.reinforcement_score == 0
    assert accuracy(skipped.correct_count, skipped.incorrect_count) is None

    with manager.transaction() as conn:
        set_id = choose_next_set(conn)
        assert set_id is not None
        session_id = start_session(conn, set_id, SESSION_NORMAL)
        word_ids = ordered_word_ids(conn, set_id, shuffle=False)
        word_id = word_ids[0]
        state = get_state(conn)
        for result in (
            RESULT_EXPOSURE,
            RESULT_EXPOSURE,
            RESULT_CORRECT,
            RESULT_CORRECT,
            RESULT_CORRECT,
            RESULT_INCORRECT,
        ):
            present_result(
                conn,
                session_id=session_id,
                word_id=word_id,
                set_id=set_id,
                result=result,
                display_mode=state.display_mode,
                case_mode=state.case_mode,
            )
        stats = load_stats(conn, word_id)
        present_result(
            conn,
            session_id=session_id,
            word_id=word_ids[1],
            set_id=set_id,
            result=RESULT_EXPOSURE,
            display_mode=state.display_mode,
            case_mode=state.case_mode,
        )
        other = load_stats(conn, word_ids[1])
        assert session_count_today(conn, int(set_id)) == 1
    assert stats.times_presented == 6
    assert stats.neutral_exposures == 2
    assert stats.correct_count == 3
    assert stats.incorrect_count == 1
    assert stats.evaluated_attempts == 4
    assert accuracy(stats.correct_count, stats.incorrect_count) == 0.75
    assert other.times_presented == 1
    assert other.correct_count == 0
    assert other.incorrect_count == 0


def test_manual_exposure_does_not_count_toward_retirement_by_default(manager: DatabaseManager) -> None:
    with manager.transaction() as conn:
        word_id = int(conn.execute("SELECT id FROM words WHERE word = 'piedra'").fetchone()["id"])
        session_id, set_id = start_manual_word_session(conn, [word_id])
        state = get_state(conn)
        present_result(
            conn,
            session_id=session_id,
            word_id=word_id,
            set_id=set_id,
            result=RESULT_EXPOSURE,
            display_mode=state.display_mode,
            case_mode=state.case_mode,
        )
        present_result(
            conn,
            session_id=session_id,
            word_id=word_id,
            set_id=set_id,
            result=RESULT_INCORRECT,
            display_mode=state.display_mode,
            case_mode=state.case_mode,
        )
        present_result(
            conn,
            session_id=session_id,
            word_id=word_id,
            set_id=set_id,
            result=RESULT_INCORRECT,
            display_mode=state.display_mode,
            case_mode=state.case_mode,
        )
        stats = load_stats(conn, word_id)
        assert stats.times_presented == 3
        assert stats.neutral_exposures == 1
        assert stats.incorrect_count == 2
        assert stats.retirement_presentations == 0
        assert stats.reinforcement_score == 2
        assert word_id in reinforcement_candidates(conn)
        word = conn.execute("SELECT state FROM words WHERE id = ?", (word_id,)).fetchone()
        assert word["state"] == "AVAILABLE"


def test_shuffle_off_keeps_set_order(manager: DatabaseManager) -> None:
    with manager.transaction() as conn:
        set_id = int(_set_named(manager, "Familia")["id"])
        labels = []
        for word_id in ordered_word_ids(conn, set_id, shuffle=False):
            labels.append(conn.execute("SELECT word FROM words WHERE id = ?", (word_id,)).fetchone()["word"])
    assert labels == ["mamá", "papá", "niño", "tío", "bebé"]
