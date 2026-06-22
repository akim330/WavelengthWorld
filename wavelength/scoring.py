from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from flask import current_app
from sqlalchemy import func

from . import db
from .models import Clue, Guess


@dataclass(frozen=True)
class ScoreResult:
    status: str
    guess_count: int
    global_average: Optional[float]
    distance: Optional[float]
    score: Optional[int]


def wavelength_score(distance: float) -> int:
    for threshold, points in current_app.config["SCORING_BANDS"]:
        if distance <= threshold:
            return points
    return 0


def clamp_position(value: float) -> float:
    dial_min = current_app.config["DIAL_MIN"]
    dial_max = current_app.config["DIAL_MAX"]
    if value < dial_min or value > dial_max:
        raise ValueError(f"Position must be between {dial_min} and {dial_max}.")
    return float(value)


def clue_stats(clue_id: int) -> tuple[int, Optional[float]]:
    count, avg = db.session.query(func.count(Guess.id), func.avg(Guess.personal_position)).filter(
        Guess.clue_id == clue_id
    ).one()
    return int(count or 0), float(avg) if avg is not None else None


def score_guess(guess: Guess) -> ScoreResult:
    count, avg = clue_stats(guess.clue_id)
    if count < current_app.config["MIN_GUESSES_FOR_SCORE"] or avg is None:
        return ScoreResult("pending", count, avg, None, None)
    distance = abs(float(guess.predicted_average_position) - avg)
    return ScoreResult("scored", count, avg, distance, wavelength_score(distance))


def score_clue(clue: Clue) -> ScoreResult:
    count, avg = clue_stats(clue.id)
    if count < current_app.config["MIN_GUESSES_FOR_SCORE"] or avg is None:
        return ScoreResult("pending", count, avg, None, None)
    distance = abs(float(clue.target_position) - avg)
    return ScoreResult("scored", count, avg, distance, wavelength_score(distance))


def round_or_none(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None
