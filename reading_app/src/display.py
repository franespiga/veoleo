"""Visual presentation of a single word."""

from __future__ import annotations

import html

from src.models import CASE_LOWER, CASE_ORIGINAL, CASE_UPPER, DISPLAY_BLACK, DISPLAY_CENTRAL, DISPLAY_DOMAN_RED

RED = "#d00000"
BLACK = "#111111"


def apply_case(word: str, case_mode: str) -> str:
    """Preserve Spanish accents. ``mamá`` becomes ``MAMÁ`` in uppercase."""
    if case_mode == CASE_UPPER:
        return word.upper()
    if case_mode == CASE_LOWER:
        return word.lower()
    if case_mode == CASE_ORIGINAL:
        return word
    raise ValueError(f"Modo de mayúsculas desconocido: {case_mode}")


def middle_index(word: str) -> int:
    """Index of the central letter. Even lengths bias toward the earlier letter."""
    if not word:
        return 0
    return (len(word) - 1) // 2


def central_letter(word: str) -> str:
    if not word:
        return ""
    return word[middle_index(word)]


def font_size_px(word: str) -> int:
    """One size for every reading word. The screen has room for the larger size."""
    return 150


def render_word_html(word: str, display_mode: str, case_mode: str, progress_label: str | None = None) -> str:
    shown = apply_case(word, case_mode)
    size = font_size_px(shown)
    inner = _letters_html(shown, display_mode)
    progress = ""
    if progress_label:
        progress = (
            f'<div style="margin-top:1.2rem;text-align:center;color:#9a9a9a;'
            f'font-size:22px;font-family:Arial,Helvetica,sans-serif;">{html.escape(progress_label)}</div>'
        )
    return (
        '<div style="background:#ffffff;min-height:48vh;display:flex;flex-direction:column;'
        'align-items:center;justify-content:center;padding:1.5rem 0.5rem 0.5rem;">'
        f'<div style="font-size:{size}px;line-height:1;font-weight:700;white-space:nowrap;'
        'font-family:\'Segoe UI\',\'Helvetica Neue\',Arial,sans-serif;letter-spacing:0.01em;">'
        f"{inner}</div>{progress}</div>"
    )


def _letters_html(shown: str, display_mode: str) -> str:
    if display_mode == DISPLAY_DOMAN_RED:
        return f'<span style="color:{RED}">{html.escape(shown)}</span>'
    if display_mode == DISPLAY_BLACK:
        return f'<span style="color:{BLACK}">{html.escape(shown)}</span>'
    if display_mode == DISPLAY_CENTRAL:
        if not shown:
            return ""
        index = middle_index(shown)
        parts: list[str] = []
        for i, char in enumerate(shown):
            color = RED if i == index else BLACK
            parts.append(f'<span style="color:{color}">{html.escape(char)}</span>')
        return "".join(parts)
    raise ValueError(f"Modo visual desconocido: {display_mode}")
