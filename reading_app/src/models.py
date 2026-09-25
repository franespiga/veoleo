"""Typed models and constants for the reading programme."""

from __future__ import annotations

from dataclasses import dataclass

WORD_AVAILABLE = "AVAILABLE"
WORD_ACTIVE = "ACTIVE"
WORD_RETIRED = "RETIRED"

SET_PLANNED = "PLANNED"
SET_ACTIVE = "ACTIVE"
SET_RETIRED = "RETIRED"

RESULT_EXPOSURE = "exposure"
RESULT_CORRECT = "correct"
RESULT_INCORRECT = "incorrect"
RESULTS = (RESULT_EXPOSURE, RESULT_CORRECT, RESULT_INCORRECT)

SESSION_NORMAL = "normal"
SESSION_REINFORCEMENT = "reinforcement"
SESSION_MANUAL = "manual"
SESSION_TYPES = (SESSION_NORMAL, SESSION_REINFORCEMENT, SESSION_MANUAL)

KIND_PROGRAMME = "programme"
KIND_REINFORCEMENT = "reinforcement"
KIND_MANUAL = "manual"

SOURCE_MIS_PALABRAS = "mis_palabras"
SOURCE_FRECUENCIA = "frecuencia"
SOURCE_AMBAS = "ambas"
VOCABULARY_SOURCES = (SOURCE_MIS_PALABRAS, SOURCE_FRECUENCIA, SOURCE_AMBAS)

DISPLAY_DOMAN_RED = "doman_red"
DISPLAY_CENTRAL = "central_letter"
DISPLAY_BLACK = "black"
DISPLAY_MODES = (DISPLAY_DOMAN_RED, DISPLAY_CENTRAL, DISPLAY_BLACK)

CASE_UPPER = "mayusculas"
CASE_LOWER = "minusculas"
CASE_ORIGINAL = "original"
CASE_MODES = (CASE_UPPER, CASE_LOWER, CASE_ORIGINAL)

PRESENTATION_PURE = "presentacion"
PRESENTATION_TRACKING = "seguimiento"
PRESENTATION_MODES = (PRESENTATION_PURE, PRESENTATION_TRACKING)

RESET_CONFIRMATION = "REINICIAR"
RECREATE_CONFIRMATION = "RECREAR"

REINFORCEMENT_THRESHOLD = 2.0


@dataclass(frozen=True)
class WordEntry:
    word: str
    source: str
    category: str | None
    rank: int | None
    enabled: bool


@dataclass
class ProgrammeState:
    programme_day: int
    created_at: str
    last_used: str
    last_calendar_date: str
    suggestion_dismissed_date: str | None
    words_per_set: int
    max_active_sets: int
    retirement_exposure_target: int
    retirement_min_days: int
    auto_retire: bool
    vocabulary_source: str
    display_mode: str
    case_mode: str
    presentation_mode: str
    shuffle_within_set: bool
    manual_counts_toward_retirement: bool


@dataclass
class WordStats:
    word_id: int
    times_presented: int = 0
    neutral_exposures: int = 0
    correct_count: int = 0
    incorrect_count: int = 0
    retirement_presentations: int = 0
    last_presented: str | None = None
    last_evaluated: str | None = None
    reinforcement_score: float = 0.0
    introduced_at: str | None = None
    introduced_programme_day: int | None = None
    retired_at: str | None = None
    retired_programme_day: int | None = None

    @property
    def evaluated_attempts(self) -> int:
        return self.correct_count + self.incorrect_count
