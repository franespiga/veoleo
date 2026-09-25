import sqlite3

from src.database import get_state
from src.database_manager import DatabaseError, DatabaseManager
from src.doman_scheduler import advance_programme_day, present_result, start_session, ordered_word_ids
from src.models import RECREATE_CONFIRMATION, RESET_CONFIRMATION, RESULT_EXPOSURE


def test_profiles_keep_independent_programme_state(manager: DatabaseManager) -> None:
    first = manager.active_name()
    manager.create_database("programa_nuevo", switch=False)
    with manager.transaction() as conn:
        advance_programme_day(conn)
        advance_programme_day(conn)
        assert get_state(conn).programme_day == 3
    manager.set_active("programa_nuevo")
    with manager.transaction() as conn:
        assert get_state(conn).programme_day == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM presentations").fetchone()["n"] == 0
    manager.set_active(first)
    with manager.transaction() as conn:
        assert get_state(conn).programme_day == 3


def test_backup_reset_recreate_and_delete(manager: DatabaseManager) -> None:
    with manager.transaction() as conn:
        advance_programme_day(conn)
        set_id = int(conn.execute("SELECT id FROM word_sets WHERE state = 'ACTIVE' LIMIT 1").fetchone()["id"])
        session_id = start_session(conn, set_id, "normal")
        word_id = ordered_word_ids(conn, set_id, shuffle=False)[0]
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
        assert get_state(conn).programme_day == 2
    manager.update_settings(max_active_sets=4)

    backup = manager.backup_active()
    assert backup.parent == manager.backup_dir
    assert "backup" in backup.name
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT programme_day FROM programme_state").fetchone()[0] == 2
        assert conn.execute("SELECT COUNT(*) FROM presentations").fetchone()[0] == 1

    try:
        manager.reset_active("no")
        raise AssertionError("debía exigir REINICIAR")
    except DatabaseError:
        pass
    manager.reset_active(RESET_CONFIRMATION)
    with manager.transaction() as conn:
        state = get_state(conn)
        assert state.programme_day == 1
        assert state.max_active_sets == 4
        assert conn.execute("SELECT COUNT(*) AS n FROM presentations").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) AS n FROM words").fetchone()["n"] > 0
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM word_sets WHERE kind = 'programme' AND state = 'ACTIVE'"
        ).fetchone()
        assert int(active["n"]) == 1
    assert (manager.data_dir / "mis_palabras.xlsx").is_file()

    with manager.transaction() as conn:
        advance_programme_day(conn)
        advance_programme_day(conn)
    manager.recreate_active(RECREATE_CONFIRMATION)
    with manager.transaction() as conn:
        assert get_state(conn).programme_day == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM presentations").fetchone()["n"] == 0
    backups = list(manager.backup_dir.glob("*.db"))
    assert len(backups) >= 2

    manager.create_database("experimento_1", switch=False)
    moved = manager.delete_database("experimento_1", "experimento_1.db")
    assert moved.parent == manager.backup_dir
    assert "experimento_1.db" not in manager.list_databases()
    assert moved.is_file()
    try:
        manager.delete_database(manager.active_name(), manager.active_name())
        raise AssertionError("no se puede borrar la única base")
    except DatabaseError:
        pass


def test_rejects_unsafe_names_and_duplicates(manager: DatabaseManager) -> None:
    try:
        manager.create_database("../fuera", switch=False)
        raise AssertionError("nombre no válido")
    except DatabaseError:
        pass
    try:
        manager.create_database("lectura_test", switch=False)
        raise AssertionError("duplicada")
    except DatabaseError:
        pass
    created = manager.create_database("lectura_octubre", switch=True)
    assert created.name == "lectura_octubre.db"
    assert manager.active_name() == "lectura_octubre.db"
    with manager.transaction() as conn:
        assert get_state(conn).programme_day == 1
