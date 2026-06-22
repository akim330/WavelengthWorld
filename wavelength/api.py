from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from . import db
from .models import Clue, CluerTask, Guess, Spectrum, User
from .moderation import normalize_clue_text, validate_clue_text
from .prompts import create_cluer_prompt, get_guesser_prompt
from .scoring import clamp_position, round_or_none, score_clue, score_guess
from .session_helpers import api_login_required, current_user, validate_csrf
from .time_utils import today_bounds_app_tz

api_bp = Blueprint("api", __name__)


@api_bp.before_request
def csrf_guard():
    if not validate_csrf():
        return jsonify({"error": "csrf_failed", "message": "Refresh the page and try again."}), 400
    return None


def score_payload(result):
    return {
        "score_status": result.status,
        "guess_count": result.guess_count,
        "global_average": round_or_none(result.global_average),
        "distance": round_or_none(result.distance),
        "score": result.score,
    }


@api_bp.get("/prompts")
@api_login_required
def prompts():
    user = current_user()
    section = request.args.get("section")
    # The play page can refresh the Guesser and Cluer panels independently.
    # Keeping this as an optional filter preserves the original all-prompts
    # response while avoiding unnecessary churn in whichever panel the player
    # is not trying to replace.
    if section == "guesser":
        return jsonify({"guesser": get_guesser_prompt(user)})
    if section == "cluer":
        return jsonify({"cluer": create_cluer_prompt(user)})
    if section:
        return jsonify({"error": "invalid_section", "message": "Prompt section must be guesser or cluer."}), 400

    return jsonify(
        {
            "guesser": get_guesser_prompt(user),
            "cluer": create_cluer_prompt(user),
        }
    )


@api_bp.post("/guesses")
@api_login_required
def submit_guess():
    user = current_user()
    data = request.get_json(silent=True) or {}

    try:
        clue_id = int(data.get("clue_id"))
        personal_position = clamp_position(float(data.get("personal_position")))
        predicted_average_position = clamp_position(float(data.get("predicted_average_position")))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_input", "message": "Both dial values must be numbers from 0 to 100."}), 400

    clue = Clue.query.get(clue_id)
    if clue is None or not clue.is_active:
        return jsonify({"error": "not_found", "message": "This clue is not available."}), 404

    if clue.author_user_id == user.id:
        return jsonify({"error": "own_clue", "message": "You cannot guess your own clue."}), 400

    guess = Guess(
        clue_id=clue.id,
        user_id=user.id,
        personal_position=personal_position,
        predicted_average_position=predicted_average_position,
    )
    db.session.add(guess)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "already_guessed", "message": "You already guessed this clue."}), 409

    result = score_guess(guess)
    payload = {"status": "ok", "guess_id": guess.id, **score_payload(result)}
    if result.status == "pending":
        payload["message"] = f"Submitted. Score will appear after {current_app.config['MIN_GUESSES_FOR_SCORE']} total guesses."
    return jsonify(payload)


@api_bp.post("/clues")
@api_login_required
def submit_clue():
    user = current_user()
    data = request.get_json(silent=True) or {}

    try:
        task_id = int(data.get("task_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid_task", "message": "Missing cluer task."}), 400

    text = str(data.get("text", "")).strip()
    is_valid, error_message = validate_clue_text(text)
    if not is_valid:
        return jsonify({"error": "invalid_clue", "message": error_message}), 400

    task = CluerTask.query.get(task_id)
    if task is None or task.user_id != user.id:
        return jsonify({"error": "invalid_task", "message": "This cluer task is not available."}), 404
    if task.used_at is not None:
        return jsonify({"error": "task_used", "message": "This cluer task has already been submitted."}), 409

    normalized_text = normalize_clue_text(text)
    clue = Clue(
        spectrum_id=task.spectrum_id,
        author_user_id=user.id,
        text=text,
        normalized_text=normalized_text,
        target_position=task.target_position,
        is_seed=False,
        is_active=True,
    )
    db.session.add(clue)
    db.session.flush()
    task.used_at = datetime.now(timezone.utc)
    task.created_clue_id = clue.id

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "duplicate_clue", "message": "That clue already exists for this spectrum."}), 409

    result = score_clue(clue)
    payload = {"status": "ok", "clue_id": clue.id, **score_payload(result)}
    if result.status == "pending":
        payload["message"] = f"Clue submitted. It will be scored after {current_app.config['MIN_GUESSES_FOR_SCORE']} people guess it."
    return jsonify(payload)


def _date_filter(query, model, period: str):
    if period == "daily":
        start, end = today_bounds_app_tz()
        query = query.filter(model.created_at >= start, model.created_at <= end)
    return query


def _leaderboard_min(period: str) -> int:
    if period == "daily":
        return int(current_app.config["DAILY_LEADERBOARD_MIN_ENTRIES"])
    return int(current_app.config["LIFETIME_LEADERBOARD_MIN_ENTRIES"])


@api_bp.get("/leaderboards")
@api_login_required
def leaderboards():
    role = request.args.get("role", "guesser")
    period = request.args.get("period", "daily")

    if role not in {"guesser", "cluer"}:
        return jsonify({"error": "invalid_role"}), 400
    if period not in {"daily", "lifetime"}:
        return jsonify({"error": "invalid_period"}), 400

    min_entries = _leaderboard_min(period)
    rows_by_user: dict[int, dict] = {}

    if role == "guesser":
        query = Guess.query.join(User)
        query = _date_filter(query, Guess, period)
        guesses = query.all()
        for guess in guesses:
            result = score_guess(guess)
            if result.score is None:
                continue
            row = rows_by_user.setdefault(
                guess.user_id,
                {
                    "username": guess.user.username_display,
                    "total_points": 0,
                    "scored_entries": 0,
                },
            )
            row["total_points"] += int(result.score)
            row["scored_entries"] += 1
    else:
        query = Clue.query.join(User, Clue.author_user_id == User.id).filter(Clue.is_seed.is_(False))
        query = _date_filter(query, Clue, period)
        clues = query.all()
        for clue in clues:
            result = score_clue(clue)
            if result.score is None:
                continue
            row = rows_by_user.setdefault(
                clue.author_user_id,
                {
                    "username": clue.author.username_display,
                    "total_points": 0,
                    "scored_entries": 0,
                },
            )
            row["total_points"] += int(result.score)
            row["scored_entries"] += 1

    rows = []
    for row in rows_by_user.values():
        if row["scored_entries"] < min_entries:
            continue
        row["average_score"] = round(row["total_points"] / row["scored_entries"], 2)
        rows.append(row)

    rows.sort(key=lambda r: (-r["average_score"], -r["scored_entries"], r["username"].lower()))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    return jsonify(
        {
            "period": period,
            "role": role,
            "minimum_scored_entries": min_entries,
            "rows": rows[:25],
        }
    )


@api_bp.get("/me/history")
@api_login_required
def history():
    user = current_user()

    guess_rows = []
    guesses = Guess.query.filter_by(user_id=user.id).order_by(Guess.created_at.desc()).limit(200).all()
    for guess in guesses:
        result = score_guess(guess)
        clue = guess.clue
        guess_rows.append(
            {
                "created_at": guess.created_at.isoformat(),
                "spectrum": clue.spectrum.label,
                "clue_text": clue.text,
                "personal_position": round(guess.personal_position, 2),
                "predicted_average_position": round(guess.predicted_average_position, 2),
                "current_global_average": round_or_none(result.global_average),
                "guess_count": result.guess_count,
                "distance": round_or_none(result.distance),
                "score": result.score,
                "status": result.status,
            }
        )

    clue_rows = []
    clues = Clue.query.filter_by(author_user_id=user.id).order_by(Clue.created_at.desc()).limit(200).all()
    for clue in clues:
        result = score_clue(clue)
        clue_rows.append(
            {
                "created_at": clue.created_at.isoformat(),
                "spectrum": clue.spectrum.label,
                "clue_text": clue.text,
                "target_position": round(clue.target_position, 2),
                "current_global_average": round_or_none(result.global_average),
                "guess_count": result.guess_count,
                "distance": round_or_none(result.distance),
                "score": result.score,
                "status": result.status,
            }
        )

    return jsonify({"guesses": guess_rows, "clues": clue_rows})


@api_bp.get("/stats")
@api_login_required
def stats():
    return jsonify(
        {
            "users": User.query.count(),
            "spectrums": Spectrum.query.count(),
            "clues": Clue.query.count(),
            "guesses": Guess.query.count(),
            "min_guesses_for_score": current_app.config["MIN_GUESSES_FOR_SCORE"],
        }
    )
