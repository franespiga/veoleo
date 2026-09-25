"""JSON API for the local reading programme. The browser owns the screen."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.database import get_state, today_iso
from src.database_manager import DatabaseError, DatabaseManager, should_suggest_day_advance
from src.doman_scheduler import (
    activate_set,
    advance_programme_day,
    choose_next_set,
    complete_session,
    create_programme_set,
    dismiss_day_suggestion,
    eligible_set_ids,
    list_sets,
    move_planned_set,
    ordered_word_ids,
    present_result,
    reinforcement_candidates,
    rename_set,
    retire_set,
    session_count_today,
    session_count_total,
    set_word_labels,
    start_manual_set_session,
    start_manual_word_session,
    start_reinforcement_session,
    start_session,
)
from src.models import SESSION_MANUAL, SESSION_NORMAL, SESSION_REINFORCEMENT
from src.statistics import history_rows, progress_summary, word_progress_rows

router = APIRouter()

SET_STATE_LABELS = {"ACTIVE": "Activo", "PLANNED": "Planificado", "RETIRED": "Retirado"}


class SessionBody(BaseModel):
    kind: str
    set_id: int | None = None
    session_type: str | None = None
    word_ids: list[int] = Field(default_factory=list)
    exclude_set_id: int | None = None


class PresentBody(BaseModel):
    word_id: int
    set_id: int | None = None
    result: str
    complete: bool = False


class SettingsBody(BaseModel):
    display_mode: str
    case_mode: str
    presentation_mode: str
    shuffle_within_set: bool
    words_per_set: int
    max_active_sets: int
    vocabulary_source: str
    retirement_exposure_target: int
    retirement_min_days: int
    auto_retire: bool
    manual_counts_toward_retirement: bool


class NameBody(BaseModel):
    name: str


class MoveBody(BaseModel):
    direction: int


class WordsBody(BaseModel):
    name: str
    word_ids: list[int]


class ConfirmBody(BaseModel):
    confirmation: str


class DeleteBody(BaseModel):
    name: str
    confirmation: str


def _manager() -> DatabaseManager:
    return DatabaseManager()


def _call(action):
    try:
        with _manager().transaction() as conn:
            return action(conn)
    except (DatabaseError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _state_payload(conn) -> dict:
    state = get_state(conn)
    payload = asdict(state)
    payload["suggest_advance"] = should_suggest_day_advance(
        state.last_calendar_date,
        state.suggestion_dismissed_date,
        today_iso(),
    )
    return payload


def _session_payload(conn, session_id: int, set_id: int, session_type: str) -> dict:
    state = get_state(conn)
    shuffle = bool(state.shuffle_within_set) if session_type in {SESSION_NORMAL, SESSION_MANUAL} else False
    word_ids = ordered_word_ids(conn, set_id, shuffle=shuffle)
    if not word_ids:
        raise ValueError("Ese set no tiene palabras.")
    words = []
    for word_id in word_ids:
        row = conn.execute("SELECT word FROM words WHERE id = ?", (word_id,)).fetchone()
        words.append({"id": word_id, "word": str(row["word"])})
    name = conn.execute("SELECT name FROM word_sets WHERE id = ?", (set_id,)).fetchone()
    return {
        "session_id": session_id,
        "set_id": set_id,
        "set_name": str(name["name"]) if name else "",
        "session_type": session_type,
        "words": words,
        "display_mode": state.display_mode,
        "case_mode": state.case_mode,
        "presentation_mode": state.presentation_mode,
    }


@router.get("/bootstrap")
def bootstrap() -> dict:
    manager = _manager()
    with manager.transaction() as conn:
        state = _state_payload(conn)
    return {"database": manager.active_name(), "state": state}


@router.get("/today")
def today() -> dict:
    def load(conn):
        state = get_state(conn)
        eligible = set(eligible_set_ids(conn))
        active_words = conn.execute("SELECT COUNT(*) AS n FROM words WHERE state = 'ACTIVE'").fetchone()
        cards = []
        for row in list_sets(conn):
            if row["state"] != "ACTIVE":
                continue
            set_id = int(row["id"])
            today_count = session_count_today(conn, set_id)
            cards.append(
                {
                    "id": set_id,
                    "name": row["name"],
                    "words": set_word_labels(conn, set_id),
                    "today": today_count,
                    "total": session_count_total(conn, set_id),
                    "eligible": set_id in eligible and not state.auto_retire,
                    "seen_today": today_count > 0,
                }
            )
        candidates = []
        for word_id in reinforcement_candidates(conn, limit=10):
            row = conn.execute(
                """
                SELECT w.word, s.incorrect_count
                FROM words w JOIN word_stats s ON s.word_id = w.id
                WHERE w.id = ?
                """,
                (word_id,),
            ).fetchone()
            candidates.append({"word_id": word_id, "word": row["word"], "incorrect_count": int(row["incorrect_count"])})
        manual_sets = [
            {"id": int(row["id"]), "name": row["name"], "state": row["state"]}
            for row in list_sets(conn)
        ]
        manual_words = [
            {"id": int(row["id"]), "word": row["word"], "category": row["category"] or ""}
            for row in conn.execute(
                "SELECT id, word, category FROM words WHERE enabled = 1 ORDER BY word"
            )
        ]
        return {
            "programme_day": state.programme_day,
            "active_sets": len(cards),
            "active_words": int(active_words["n"]),
            "suggest_advance": should_suggest_day_advance(
                state.last_calendar_date, state.suggestion_dismissed_date, today_iso()
            ),
            "sets": cards,
            "reinforcement": candidates,
            "manual_sets": manual_sets,
            "manual_words": manual_words,
        }

    return _call(load)


@router.post("/programme/advance")
def advance() -> dict:
    day = _call(lambda conn: advance_programme_day(conn, today=today_iso()))
    return {"programme_day": day}


@router.post("/programme/dismiss-suggestion")
def dismiss() -> dict:
    _call(lambda conn: dismiss_day_suggestion(conn, today_iso()))
    return {"ok": True}


@router.post("/sessions")
def open_session(body: SessionBody) -> dict:
    def start(conn):
        kind = body.kind
        if kind == "next":
            set_id = choose_next_set(conn, exclude_set_id=body.exclude_set_id)
            if set_id is None:
                raise ValueError("No hay un set activo para presentar.")
            session_id = start_session(conn, set_id, SESSION_NORMAL)
            return _session_payload(conn, session_id, set_id, SESSION_NORMAL)
        if kind == "set":
            if body.set_id is None:
                raise ValueError("Falta el set.")
            session_type = body.session_type or SESSION_NORMAL
            if session_type == SESSION_MANUAL:
                session_id = start_manual_set_session(conn, body.set_id)
            else:
                session_id = start_session(conn, body.set_id, SESSION_NORMAL)
                session_type = SESSION_NORMAL
            return _session_payload(conn, session_id, body.set_id, session_type)
        if kind == "reinforcement":
            started = start_reinforcement_session(conn)
            if started is None:
                raise ValueError("No hay palabras con dificultades repetidas.")
            session_id, set_id = started
            return _session_payload(conn, session_id, set_id, SESSION_REINFORCEMENT)
        if kind == "words":
            session_id, set_id = start_manual_word_session(conn, body.word_ids)
            return _session_payload(conn, session_id, set_id, SESSION_MANUAL)
        if kind == "repeat":
            if body.set_id is None:
                raise ValueError("Falta el set.")
            session_type = body.session_type or SESSION_NORMAL
            if session_type == SESSION_REINFORCEMENT:
                session_id = start_session(
                    conn, body.set_id, SESSION_REINFORCEMENT, counts_toward_retirement=False
                )
            elif session_type == SESSION_MANUAL:
                session_id = start_manual_set_session(conn, body.set_id)
            else:
                session_id = start_session(conn, body.set_id, SESSION_NORMAL)
                session_type = SESSION_NORMAL
            return _session_payload(conn, session_id, body.set_id, session_type)
        raise ValueError("No se reconoce esa presentación.")

    return _call(start)


@router.post("/sessions/{session_id}/present")
def present(session_id: int, body: PresentBody) -> dict:
    def record(conn):
        state = get_state(conn)
        present_result(
            conn,
            session_id=session_id,
            word_id=body.word_id,
            set_id=body.set_id,
            result=body.result,
            display_mode=state.display_mode,
            case_mode=state.case_mode,
        )
        if body.complete:
            complete_session(conn, session_id)
        return {"ok": True}

    return _call(record)


@router.post("/sessions/{session_id}/complete")
def finish(session_id: int) -> dict:
    _call(lambda conn: complete_session(conn, session_id))
    return {"ok": True}


@router.get("/progress")
def progress() -> dict:
    def load(conn):
        summary = asdict(progress_summary(conn))
        return {"summary": summary, "words": word_progress_rows(conn)}

    return _call(load)


@router.get("/history")
def history(
    calendar_date: str | None = None,
    programme_day: int | None = None,
    set_id: int | None = None,
    word_id: int | None = None,
) -> dict:
    def load(conn):
        sets = [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "state": SET_STATE_LABELS.get(row["state"], row["state"]),
            }
            for row in list_sets(conn)
        ]
        words = [
            {"id": int(row["id"]), "word": row["word"]}
            for row in conn.execute(
                """
                SELECT DISTINCT w.id, w.word FROM words w
                JOIN presentations p ON p.word_id = w.id
                ORDER BY w.word
                """
            )
        ]
        days = [
            int(row["programme_day"])
            for row in conn.execute(
                "SELECT DISTINCT programme_day FROM presentations ORDER BY programme_day"
            )
        ]
        rows = history_rows(
            conn,
            calendar_date=calendar_date or None,
            programme_day=programme_day,
            set_id=set_id,
            word_id=word_id,
        )
        return {"sets": sets, "words": words, "days": days, "rows": rows}

    return _call(load)


@router.get("/sets")
def sets_page() -> dict:
    def load(conn):
        state = get_state(conn)
        cards = []
        for row in list_sets(conn):
            set_id = int(row["id"])
            cards.append(
                {
                    "id": set_id,
                    "name": row["name"],
                    "state": row["state"],
                    "state_label": SET_STATE_LABELS.get(row["state"], row["state"]),
                    "words": set_word_labels(conn, set_id),
                    "today": session_count_today(conn, set_id),
                    "total": session_count_total(conn, set_id),
                }
            )
        available = []
        for row in conn.execute(
            """
            SELECT w.id, w.word, w.category, w.state
            FROM words w
            WHERE w.enabled = 1
              AND NOT EXISTS (
                SELECT 1 FROM set_words sw
                JOIN word_sets ws ON ws.id = sw.set_id
                WHERE sw.word_id = w.id AND ws.kind = 'programme' AND ws.state IN ('PLANNED', 'ACTIVE')
              )
            ORDER BY w.word
            """
        ):
            available.append(
                {
                    "id": int(row["id"]),
                    "word": row["word"],
                    "category": row["category"] or "",
                    "state": row["state"],
                }
            )
        return {"words_per_set": state.words_per_set, "sets": cards, "available": available}

    return _call(load)


@router.post("/sets")
def create_set(body: WordsBody) -> dict:
    set_id = _call(lambda conn: create_programme_set(conn, body.name, body.word_ids))
    return {"id": set_id}


@router.post("/sets/{set_id}/rename")
def rename(set_id: int, body: NameBody) -> dict:
    _call(lambda conn: rename_set(conn, set_id, body.name))
    return {"ok": True}


@router.post("/sets/{set_id}/activate")
def activate(set_id: int) -> dict:
    _call(lambda conn: activate_set(conn, set_id))
    return {"ok": True}


@router.post("/sets/{set_id}/retire")
def retire(set_id: int) -> dict:
    _call(lambda conn: retire_set(conn, set_id))
    return {"ok": True}


@router.post("/sets/{set_id}/move")
def move(set_id: int, body: MoveBody) -> dict:
    _call(lambda conn: move_planned_set(conn, set_id, body.direction))
    return {"ok": True}


@router.get("/settings")
def settings() -> dict:
    manager = _manager()
    with manager.transaction() as conn:
        state = _state_payload(conn)
    return {"state": state, "databases": manager.list_databases(), "active": manager.active_name()}


@router.put("/settings")
def save_settings(body: SettingsBody) -> dict:
    try:
        _manager().update_settings(**body.model_dump())
    except DatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/vocabulary/sync")
def sync() -> dict:
    try:
        count = _manager().sync_active()
    except (DatabaseError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"count": count}


@router.post("/databases/active")
def use_database(body: NameBody) -> dict:
    try:
        _manager().set_active(body.name)
    except DatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"active": _manager().active_name()}


@router.post("/databases")
def create_database(body: NameBody) -> dict:
    try:
        _manager().create_database(body.name, switch=True)
    except DatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"active": _manager().active_name()}


@router.post("/databases/backup")
def backup() -> dict:
    try:
        path = _manager().backup_active()
    except DatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": str(path)}


@router.post("/databases/reset")
def reset(body: ConfirmBody) -> dict:
    try:
        _manager().reset_active(body.confirmation.strip())
    except DatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/databases/recreate")
def recreate(body: ConfirmBody) -> dict:
    try:
        _manager().recreate_active(body.confirmation.strip())
    except DatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/databases/delete")
def delete_database(body: DeleteBody) -> dict:
    try:
        path = _manager().delete_database(body.name, body.confirmation.strip())
    except DatabaseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"path": str(path), "active": _manager().active_name()}
