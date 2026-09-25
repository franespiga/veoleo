"""Accuracy and aggregate reporting.

Neutral exposures count as presentations and never as evaluated attempts.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.models import RESULT_CORRECT, RESULT_EXPOSURE, RESULT_INCORRECT, WordStats


def evaluated_attempts(correct_count: int, incorrect_count: int) -> int:
    return correct_count + incorrect_count


def accuracy(correct_count: int, incorrect_count: int) -> float | None:
    """Return accuracy over evaluated attempts only.

    ``None`` means the word has not been evaluated. Callers should display
    ``Sin evaluar`` rather than 0%.
    """
    total = evaluated_attempts(correct_count, incorrect_count)
    if total == 0:
        return None
    return correct_count / total


def format_accuracy(correct_count: int, incorrect_count: int) -> str:
    value = accuracy(correct_count, incorrect_count)
    if value is None:
        return "Sin evaluar"
    return f"{value * 100:.0f}%"


def apply_result(stats: WordStats, result: str, counts_toward_retirement: bool, timestamp: str) -> None:
    """Update counters for one presentation. Exposure does not touch accuracy fields."""
    if result not in {RESULT_EXPOSURE, RESULT_CORRECT, RESULT_INCORRECT}:
        raise ValueError(f"Resultado desconocido: {result}")
    stats.times_presented += 1
    stats.last_presented = timestamp
    if result == RESULT_EXPOSURE:
        stats.neutral_exposures += 1
    elif result == RESULT_CORRECT:
        stats.correct_count += 1
        stats.last_evaluated = timestamp
        stats.reinforcement_score = max(0.0, stats.reinforcement_score - 0.5)
    else:
        stats.incorrect_count += 1
        stats.last_evaluated = timestamp
        stats.reinforcement_score += 1.0
    if counts_toward_retirement:
        stats.retirement_presentations += 1
    _assert_presentation_invariant(stats)


def _assert_presentation_invariant(stats: WordStats) -> None:
    expected = stats.neutral_exposures + stats.correct_count + stats.incorrect_count
    if stats.times_presented != expected:
        raise RuntimeError("times_presented no coincide con la suma de resultados")


def days_active(introduced_programme_day: int | None, programme_day: int) -> int:
    if introduced_programme_day is None:
        return 0
    return programme_day - introduced_programme_day + 1


def retirement_eligible(
    retirement_presentations: int,
    introduced_programme_day: int | None,
    programme_day: int,
    exposure_target: int,
    min_days: int,
) -> bool:
    if introduced_programme_day is None:
        return False
    return retirement_presentations >= exposure_target and days_active(
        introduced_programme_day, programme_day
    ) >= min_days


@dataclass
class ProgressSummary:
    programme_day: int
    total_presentations: int
    neutral_exposures: int
    evaluated_readings: int
    correct_readings: int
    incorrect_readings: int
    active_words: int
    retired_words: int
    active_sets: int
    retired_sets: int


def progress_summary(conn: sqlite3.Connection) -> ProgressSummary:
    state = conn.execute("SELECT programme_day FROM programme_state WHERE id = 1").fetchone()
    totals = conn.execute(
        """
        SELECT
            COALESCE(SUM(times_presented), 0) AS presented,
            COALESCE(SUM(neutral_exposures), 0) AS exposures,
            COALESCE(SUM(correct_count), 0) AS correct,
            COALESCE(SUM(incorrect_count), 0) AS incorrect
        FROM word_stats
        """
    ).fetchone()
    words = conn.execute(
        """
        SELECT
            SUM(CASE WHEN state = 'ACTIVE' THEN 1 ELSE 0 END) AS active_words,
            SUM(CASE WHEN state = 'RETIRED' THEN 1 ELSE 0 END) AS retired_words
        FROM words
        """
    ).fetchone()
    sets = conn.execute(
        """
        SELECT
            SUM(CASE WHEN state = 'ACTIVE' AND kind = 'programme' THEN 1 ELSE 0 END) AS active_sets,
            SUM(CASE WHEN state = 'RETIRED' AND kind = 'programme' THEN 1 ELSE 0 END) AS retired_sets
        FROM word_sets
        """
    ).fetchone()
    correct = int(totals["correct"])
    incorrect = int(totals["incorrect"])
    return ProgressSummary(
        programme_day=int(state["programme_day"]),
        total_presentations=int(totals["presented"]),
        neutral_exposures=int(totals["exposures"]),
        evaluated_readings=correct + incorrect,
        correct_readings=correct,
        incorrect_readings=incorrect,
        active_words=int(words["active_words"] or 0),
        retired_words=int(words["retired_words"] or 0),
        active_sets=int(sets["active_sets"] or 0),
        retired_sets=int(sets["retired_sets"] or 0),
    )


def word_progress_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
            w.word AS palabra,
            COALESCE(
                (
                    SELECT ws.name
                    FROM set_words sw
                    JOIN word_sets ws ON ws.id = sw.set_id
                    WHERE sw.word_id = w.id AND ws.kind = 'programme'
                    ORDER BY CASE ws.state WHEN 'ACTIVE' THEN 0 WHEN 'PLANNED' THEN 1 ELSE 2 END, ws.id DESC
                    LIMIT 1
                ),
                ''
            ) AS set_name,
            w.state AS estado,
            COALESCE(s.times_presented, 0) AS presentaciones,
            (
                SELECT COUNT(*) FROM presentations p
                WHERE p.word_id = w.id
                  AND p.programme_day = (SELECT programme_day FROM programme_state WHERE id = 1)
            ) AS presentaciones_hoy,
            COALESCE(s.neutral_exposures, 0) AS exposiciones,
            COALESCE(s.correct_count, 0) AS correctas,
            COALESCE(s.incorrect_count, 0) AS incorrectas,
            s.introduced_programme_day AS dia_introducida,
            s.last_presented AS ultima_presentacion
        FROM words w
        LEFT JOIN word_stats s ON s.word_id = w.id
        WHERE COALESCE(s.times_presented, 0) > 0 OR w.state != 'AVAILABLE'
        ORDER BY
            CASE w.state WHEN 'ACTIVE' THEN 0 WHEN 'RETIRED' THEN 1 ELSE 2 END,
            palabra
        """
    ).fetchall()
    table: list[dict[str, object]] = []
    for row in rows:
        table.append(
            {
                "Palabra": row["palabra"],
                "Set": row["set_name"],
                "Estado": _state_label(row["estado"]),
                "Presentaciones": int(row["presentaciones"]),
                "Presentaciones hoy": int(row["presentaciones_hoy"]),
                "Exposiciones": int(row["exposiciones"]),
                "Correctas": int(row["correctas"]),
                "Incorrectas": int(row["incorrectas"]),
                "Precisión evaluada": format_accuracy(int(row["correctas"]), int(row["incorrectas"])),
                "Día introducida": row["dia_introducida"] if row["dia_introducida"] is not None else "",
                "Última presentación": _short_timestamp(row["ultima_presentacion"]),
            }
        )
    return table


def history_rows(
    conn: sqlite3.Connection,
    *,
    calendar_date: str | None = None,
    programme_day: int | None = None,
    set_id: int | None = None,
    word_id: int | None = None,
) -> list[dict[str, object]]:
    clauses = ["1 = 1"]
    params: list[object] = []
    if calendar_date:
        clauses.append("substr(p.timestamp, 1, 10) = ?")
        params.append(calendar_date)
    if programme_day is not None:
        clauses.append("p.programme_day = ?")
        params.append(programme_day)
    if set_id is not None:
        clauses.append("p.set_id = ?")
        params.append(set_id)
    if word_id is not None:
        clauses.append("p.word_id = ?")
        params.append(word_id)
    where = " AND ".join(clauses)
    grouped = conn.execute(
        f"""
        SELECT
            substr(p.timestamp, 1, 10) AS day,
            p.programme_day AS programme_day,
            COALESCE(ws.name, 'Presentación libre') AS set_name,
            p.set_id AS set_id,
            COUNT(DISTINCT p.session_id) AS sessions,
            COUNT(*) AS presentations,
            SUM(CASE WHEN p.result = 'exposure' THEN 1 ELSE 0 END) AS exposures,
            SUM(CASE WHEN p.result = 'correct' THEN 1 ELSE 0 END) AS correct,
            SUM(CASE WHEN p.result = 'incorrect' THEN 1 ELSE 0 END) AS incorrect
        FROM presentations p
        LEFT JOIN word_sets ws ON ws.id = p.set_id
        WHERE {where}
        GROUP BY substr(p.timestamp, 1, 10), p.programme_day, p.set_id
        ORDER BY day DESC, set_name
        """,
        params,
    ).fetchall()
    rows: list[dict[str, object]] = []
    for row in grouped:
        iso_day = str(row["day"])
        pretty = _pretty_date(iso_day)
        rows.append(
            {
                "Fecha": pretty,
                "Día del programa": int(row["programme_day"]),
                "Set": row["set_name"],
                "Sesiones": int(row["sessions"]),
                "Presentaciones": int(row["presentations"]),
                "Exposiciones": int(row["exposures"]),
                "Correctas": int(row["correct"]),
                "Incorrectas": int(row["incorrect"]),
            }
        )
    return rows


def _state_label(state: str) -> str:
    return {"AVAILABLE": "Disponible", "ACTIVE": "Activa", "RETIRED": "Retirada"}.get(state, state)


def _short_timestamp(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("T", " ")[:16]


def _pretty_date(iso_day: str) -> str:
    parts = iso_day.split("-")
    if len(parts) != 3:
        return iso_day
    year, month, day = parts
    return f"{day}/{month}/{year}"
