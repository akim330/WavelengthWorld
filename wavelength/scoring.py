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
    opinion_count: int
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


def clue_opinion_stats(clue: Clue) -> tuple[int, float]:
    """
    Return the total opinion count and average used to score a clue.

    The target position assigned when the clue was written is the first opinion.
    Each player's personal position adds one equally weighted opinion after that,
    so even a clue with no player responses has one opinion and a defined average.
    """
    player_count, player_position_sum = db.session.query(
        func.count(Guess.id),
        func.sum(Guess.personal_position),
    ).filter(Guess.clue_id == clue.id).one()

    opinion_count = int(player_count or 0) + 1
    opinion_sum = float(clue.target_position) + float(player_position_sum or 0.0)
    return opinion_count, opinion_sum / opinion_count


def score_guess(guess: Guess) -> ScoreResult:
    opinion_count, avg = clue_opinion_stats(guess.clue)
    if opinion_count < current_app.config["MIN_OPINIONS_FOR_SCORE"]:
        return ScoreResult("pending", opinion_count, avg, None, None)
    distance = abs(float(guess.predicted_average_position) - avg)
    return ScoreResult("scored", opinion_count, avg, distance, wavelength_score(distance))


def score_clue(clue: Clue) -> ScoreResult:
    opinion_count, avg = clue_opinion_stats(clue)
    if opinion_count < current_app.config["MIN_OPINIONS_FOR_SCORE"]:
        return ScoreResult("pending", opinion_count, avg, None, None)
    distance = abs(float(clue.target_position) - avg)
    return ScoreResult("scored", opinion_count, avg, distance, wavelength_score(distance))


def round_or_none(value: Optional[float], digits: int = 2) -> Optional[float]:
    return round(value, digits) if value is not None else None
