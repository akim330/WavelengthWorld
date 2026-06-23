from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from . import db
from .models import Clue, CluerTask, FriendRequest, Friendship, Guess, Spectrum, User
from .moderation import normalize_clue_text, normalize_username, validate_clue_text
from .prompts import create_cluer_prompt, get_guesser_prompt
from .scoring import clamp_position, round_or_none, score_clue, score_guess
from .session_helpers import api_login_required, current_user, validate_csrf
from .time_utils import today_bounds_app_tz, week_bounds_app_tz

api_bp = Blueprint("api", __name__)

PENDING_FRIEND_REQUEST = "pending"
ACCEPTED_FRIEND_REQUEST = "accepted"
DECLINED_FRIEND_REQUEST = "declined"
CANCELED_FRIEND_REQUEST = "canceled"


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


def ordered_friend_pair(first_user_id: int, second_user_id: int) -> tuple[int, int]:
    # Friendships are stored once for both directions. Sorting the ids before
    # querying or inserting keeps every caller using the same canonical pair.
    return (first_user_id, second_user_id) if first_user_id < second_user_id else (second_user_id, first_user_id)


def friendship_between(first_user_id: int, second_user_id: int) -> Friendship | None:
    low_id, high_id = ordered_friend_pair(first_user_id, second_user_id)
    return Friendship.query.filter_by(user_low_id=low_id, user_high_id=high_id).first()


def are_friends(first_user_id: int, second_user_id: int) -> bool:
    return friendship_between(first_user_id, second_user_id) is not None


def serialize_friend(user: User) -> dict:
    return {"id": user.id, "username": user.username_display}


def serialize_friend_request(friend_request: FriendRequest, other_user: User) -> dict:
    return {
        "id": friend_request.id,
        "username": other_user.username_display,
        "created_at": friend_request.created_at.isoformat(),
    }


def serialize_friend_request_list(friend_requests: list[FriendRequest], direction: str) -> list[dict]:
    rows = []
    for friend_request in friend_requests:
        other_user = friend_request.requester if direction == "incoming" else friend_request.addressee
        if other_user is None:
            current_app.logger.error("Friend request %s points at a missing %s user.", friend_request.id, direction)
            continue
        rows.append(serialize_friend_request(friend_request, other_user))
    return rows


def reject_guest_social_user(user: User | None):
    # Guest accounts are temporary identities with no recovery path, so social
    # features are blocked at the API layer even if a guest reaches these
    # endpoints through a stale page, copied URL, or manual request.
    if user is None:
        current_app.logger.error("api_login_required allowed a missing user into a friends endpoint.")
        return jsonify({"error": "login_required"}), 401
    if user.is_guest:
        return jsonify({"error": "guest_not_allowed", "message": "Create an account to use friends."}), 403
    return None


def serialize_spectrum_poles(spectrum: Spectrum) -> dict:
    # Friend comparison diagrams show the spectrum poles directly under the arc,
    # so the API returns the two endpoint labels separately instead of forcing
    # the browser to split the combined display label.
    return {
        "spectrum_left_label": spectrum.left_label,
        "spectrum_right_label": spectrum.right_label,
    }


def pending_request_between(first_user_id: int, second_user_id: int) -> FriendRequest | None:
    # Pending requests should be unique regardless of who initiated the request,
    # because a reverse pending request would leave both players waiting on each
    # other instead of creating one clear accept/decline action.
    return FriendRequest.query.filter(
        FriendRequest.status == PENDING_FRIEND_REQUEST,
        or_(
            (FriendRequest.requester_user_id == first_user_id) & (FriendRequest.addressee_user_id == second_user_id),
            (FriendRequest.requester_user_id == second_user_id) & (FriendRequest.addressee_user_id == first_user_id),
        ),
    ).first()


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


@api_bp.get("/me/settings")
@api_login_required
def settings():
    user = current_user()
    return jsonify(
        {
            "show_on_leaderboards": user.show_on_leaderboards,
        }
    )


@api_bp.post("/me/settings")
@api_login_required
def update_settings():
    user = current_user()
    data = request.get_json(silent=True) or {}

    if "show_on_leaderboards" not in data or not isinstance(data["show_on_leaderboards"], bool):
        return jsonify({"error": "invalid_settings", "message": "Leaderboard visibility must be true or false."}), 400

    # The leaderboard opt-out is intentionally narrow: it only hides public
    # leaderboard rows, while personal history and scoring continue to work.
    user.show_on_leaderboards = data["show_on_leaderboards"]
    db.session.commit()
    return jsonify(
        {
            "show_on_leaderboards": user.show_on_leaderboards,
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
    if clue is None or not clue.is_active or not clue.spectrum.is_active:
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
    if task.spectrum is None:
        current_app.logger.error("Cluer task %s has no spectrum and cannot create a clue.", task.id)
        return jsonify({"error": "invalid_task", "message": "This cluer task is not available."}), 404
    if not task.spectrum.is_active:
        return jsonify({"error": "inactive_spectrum", "message": "This spectrum is no longer available."}), 409

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
    elif period == "weekly":
        start, end = week_bounds_app_tz()
        query = query.filter(model.created_at >= start, model.created_at <= end)
    return query


def _leaderboard_min(period: str) -> int:
    if period == "daily":
        return int(current_app.config["DAILY_LEADERBOARD_MIN_ENTRIES"])
    if period == "weekly":
        return int(current_app.config["WEEKLY_LEADERBOARD_MIN_ENTRIES"])
    return int(current_app.config["ALL_TIME_LEADERBOARD_MIN_ENTRIES"])


@api_bp.get("/leaderboards")
@api_login_required
def leaderboards():
    role = request.args.get("role", "guesser")
    period = request.args.get("period", "all_time")

    if role not in {"guesser", "cluer"}:
        return jsonify({"error": "invalid_role"}), 400
    if period == "lifetime":
        period = "all_time"
    if period not in {"daily", "weekly", "all_time"}:
        return jsonify({"error": "invalid_period"}), 400

    min_entries = _leaderboard_min(period)
    rows_by_user: dict[int, dict] = {}

    if role == "guesser":
        # Deleted seed-catalog spectrums leave their historical rows in the
        # database as inactive records, so leaderboard scoring must explicitly
        # ignore guesses whose clue or spectrum has been suppressed.
        query = (
            Guess.query.join(Clue)
            .join(Spectrum)
            .join(User, Guess.user_id == User.id)
            .filter(
                Clue.is_active.is_(True),
                Spectrum.is_active.is_(True),
                User.show_on_leaderboards.is_(True),
                User.is_guest.is_(False),
            )
        )
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
        # Cluer leaderboards follow the same suppression rules as prompts:
        # inactive clues and clues on inactive spectrums should not contribute
        # score after a spectrum has been removed from the active catalog.
        query = (
            Clue.query.join(User, Clue.author_user_id == User.id)
            .join(Spectrum)
            .filter(
                Clue.is_seed.is_(False),
                Clue.is_active.is_(True),
                Spectrum.is_active.is_(True),
                User.show_on_leaderboards.is_(True),
                User.is_guest.is_(False),
            )
        )
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


@api_bp.get("/friends")
@api_login_required
def friends():
    user = current_user()
    guest_response = reject_guest_social_user(user)
    if guest_response is not None:
        return guest_response

    friendships = Friendship.query.filter(
        or_(Friendship.user_low_id == user.id, Friendship.user_high_id == user.id)
    ).all()

    friend_rows = []
    for friendship in friendships:
        friend_user = friendship.user_high if friendship.user_low_id == user.id else friendship.user_low
        if friend_user is None:
            current_app.logger.error("Friendship %s points at a missing user.", friendship.id)
            continue
        friend_rows.append(serialize_friend(friend_user))
    friend_rows.sort(key=lambda row: row["username"].lower())

    incoming_requests = (
        FriendRequest.query.join(User, FriendRequest.requester_user_id == User.id)
        .filter(FriendRequest.addressee_user_id == user.id, FriendRequest.status == PENDING_FRIEND_REQUEST)
        .order_by(FriendRequest.created_at.desc())
        .all()
    )
    outgoing_requests = (
        FriendRequest.query.join(User, FriendRequest.addressee_user_id == User.id)
        .filter(FriendRequest.requester_user_id == user.id, FriendRequest.status == PENDING_FRIEND_REQUEST)
        .order_by(FriendRequest.created_at.desc())
        .all()
    )

    return jsonify(
        {
            "friends": friend_rows,
            "incoming_requests": serialize_friend_request_list(incoming_requests, "incoming"),
            "outgoing_requests": serialize_friend_request_list(outgoing_requests, "outgoing"),
        }
    )


@api_bp.post("/friend-requests")
@api_login_required
def create_friend_request():
    user = current_user()
    guest_response = reject_guest_social_user(user)
    if guest_response is not None:
        return guest_response

    data = request.get_json(silent=True) or {}
    username_display = str(data.get("username", "")).strip()
    username_normalized = normalize_username(username_display)

    if not username_normalized:
        return jsonify({"error": "missing_username", "message": "Enter a username to request."}), 400

    addressee = User.query.filter_by(username_normalized=username_normalized).first()
    if addressee is None:
        return jsonify({"error": "user_not_found", "message": "No user was found with that username."}), 404
    if addressee.is_guest:
        return jsonify({"error": "guest_not_allowed", "message": "Guest players cannot use friends."}), 400
    if addressee.id == user.id:
        return jsonify({"error": "self_request", "message": "You cannot send a friend request to yourself."}), 400
    if are_friends(user.id, addressee.id):
        return jsonify({"error": "already_friends", "message": "You are already friends with that user."}), 409
    if pending_request_between(user.id, addressee.id) is not None:
        return jsonify({"error": "request_pending", "message": "A friend request is already pending between you."}), 409

    friend_request = FriendRequest(
        requester_user_id=user.id,
        addressee_user_id=addressee.id,
        status=PENDING_FRIEND_REQUEST,
    )
    db.session.add(friend_request)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "request_pending", "message": "A friend request is already pending between you."}), 409

    return jsonify({"status": "ok", "request": serialize_friend_request(friend_request, addressee)})


def pending_request_for_user(request_id: int, user_id: int) -> FriendRequest | None:
    # Request actions must only operate on pending requests involving the current
    # user, otherwise stale or guessed ids could alter completed request history.
    return FriendRequest.query.filter(
        FriendRequest.id == request_id,
        FriendRequest.status == PENDING_FRIEND_REQUEST,
        or_(FriendRequest.requester_user_id == user_id, FriendRequest.addressee_user_id == user_id),
    ).first()


@api_bp.post("/friend-requests/<int:request_id>/accept")
@api_login_required
def accept_friend_request(request_id: int):
    user = current_user()
    guest_response = reject_guest_social_user(user)
    if guest_response is not None:
        return guest_response

    friend_request = pending_request_for_user(request_id, user.id)
    if friend_request is None:
        return jsonify({"error": "request_not_found", "message": "That pending friend request was not found."}), 404
    if friend_request.addressee_user_id != user.id:
        return jsonify({"error": "not_allowed", "message": "Only the recipient can accept this request."}), 403

    if friend_request.requester is None or friend_request.addressee is None:
        current_app.logger.error("Friend request %s points at a missing user.", friend_request.id)
        return jsonify({"error": "request_not_found", "message": "That pending friend request was not found."}), 404

    low_id, high_id = ordered_friend_pair(friend_request.requester_user_id, friend_request.addressee_user_id)
    friend_request.status = ACCEPTED_FRIEND_REQUEST
    if friendship_between(friend_request.requester_user_id, friend_request.addressee_user_id) is None:
        db.session.add(Friendship(user_low_id=low_id, user_high_id=high_id))

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "already_friends", "message": "You are already friends with that user."}), 409

    return jsonify({"status": "ok", "friend": serialize_friend(friend_request.requester)})


@api_bp.post("/friend-requests/<int:request_id>/decline")
@api_login_required
def decline_friend_request(request_id: int):
    user = current_user()
    guest_response = reject_guest_social_user(user)
    if guest_response is not None:
        return guest_response

    friend_request = pending_request_for_user(request_id, user.id)
    if friend_request is None:
        return jsonify({"error": "request_not_found", "message": "That pending friend request was not found."}), 404
    if friend_request.addressee_user_id != user.id:
        return jsonify({"error": "not_allowed", "message": "Only the recipient can decline this request."}), 403

    friend_request.status = DECLINED_FRIEND_REQUEST
    db.session.commit()
    return jsonify({"status": "ok"})


@api_bp.post("/friend-requests/<int:request_id>/cancel")
@api_login_required
def cancel_friend_request(request_id: int):
    user = current_user()
    guest_response = reject_guest_social_user(user)
    if guest_response is not None:
        return guest_response

    friend_request = pending_request_for_user(request_id, user.id)
    if friend_request is None:
        return jsonify({"error": "request_not_found", "message": "That pending friend request was not found."}), 404
    if friend_request.requester_user_id != user.id:
        return jsonify({"error": "not_allowed", "message": "Only the sender can cancel this request."}), 403

    friend_request.status = CANCELED_FRIEND_REQUEST
    db.session.commit()
    return jsonify({"status": "ok"})


@api_bp.get("/friends/<int:friend_id>/comparison")
@api_login_required
def friend_comparison(friend_id: int):
    user = current_user()
    guest_response = reject_guest_social_user(user)
    if guest_response is not None:
        return guest_response

    friend = User.query.get(friend_id)
    if friend is None:
        return jsonify({"error": "friend_not_found", "message": "That friend was not found."}), 404
    if friend.is_guest:
        return jsonify({"error": "guest_not_allowed", "message": "Guest players cannot use friends."}), 400
    if not are_friends(user.id, friend.id):
        return jsonify({"error": "not_friends", "message": "You can only compare answers with friends."}), 403

    FriendGuess = aliased(Guess)
    shared_guesses = (
        Guess.query.join(Clue, Guess.clue_id == Clue.id)
        .join(Spectrum, Clue.spectrum_id == Spectrum.id)
        .join(FriendGuess, (FriendGuess.clue_id == Guess.clue_id) & (FriendGuess.user_id == friend.id))
        .filter(
            Guess.user_id == user.id,
            Clue.is_active.is_(True),
            Spectrum.is_active.is_(True),
        )
        .order_by(Guess.created_at.desc())
        .limit(200)
        .all()
    )

    guess_rows = []
    for guess in shared_guesses:
        friend_guess = next((candidate for candidate in guess.clue.guesses if candidate.user_id == friend.id), None)
        if friend_guess is None:
            current_app.logger.error("Shared guess query returned clue %s without friend guess for user %s.", guess.clue_id, friend.id)
            continue
        result = score_guess(guess)
        clue = guess.clue
        guess_rows.append(
            {
                "created_at": guess.created_at.isoformat(),
                "spectrum": clue.spectrum.label,
                **serialize_spectrum_poles(clue.spectrum),
                "clue_text": clue.text,
                "your_predicted_average_position": round(guess.predicted_average_position, 2),
                "friend_predicted_average_position": round(friend_guess.predicted_average_position, 2),
                "current_global_average": round_or_none(result.global_average),
                "guess_count": result.guess_count,
                "status": result.status,
            }
        )

    friend_clues = (
        Guess.query.join(Clue, Guess.clue_id == Clue.id)
        .join(Spectrum, Clue.spectrum_id == Spectrum.id)
        .filter(
            Guess.user_id == user.id,
            Clue.author_user_id == friend.id,
            Clue.is_active.is_(True),
            Spectrum.is_active.is_(True),
        )
        .order_by(Clue.created_at.desc())
        .limit(200)
        .all()
    )

    clue_rows = []
    for guess in friend_clues:
        clue = guess.clue
        result = score_clue(clue)
        clue_rows.append(
            {
                "created_at": clue.created_at.isoformat(),
                "spectrum": clue.spectrum.label,
                **serialize_spectrum_poles(clue.spectrum),
                "clue_text": clue.text,
                "friend_target_position": round(clue.target_position, 2),
                "your_predicted_average_position": round(guess.predicted_average_position, 2),
                "current_global_average": round_or_none(result.global_average),
                "guess_count": result.guess_count,
                "status": result.status,
            }
        )

    your_clues = (
        Guess.query.join(Clue, Guess.clue_id == Clue.id)
        .join(Spectrum, Clue.spectrum_id == Spectrum.id)
        .filter(
            Guess.user_id == friend.id,
            Clue.author_user_id == user.id,
            Clue.is_active.is_(True),
            Spectrum.is_active.is_(True),
        )
        .order_by(Clue.created_at.desc())
        .limit(200)
        .all()
    )

    your_clue_rows = []
    for guess in your_clues:
        clue = guess.clue
        result = score_clue(clue)
        your_clue_rows.append(
            {
                "created_at": clue.created_at.isoformat(),
                "spectrum": clue.spectrum.label,
                **serialize_spectrum_poles(clue.spectrum),
                "clue_text": clue.text,
                "your_target_position": round(clue.target_position, 2),
                "friend_predicted_average_position": round(guess.predicted_average_position, 2),
                "current_global_average": round_or_none(result.global_average),
                "guess_count": result.guess_count,
                "status": result.status,
            }
        )

    return jsonify({"friend": serialize_friend(friend), "guesses": guess_rows, "clues": clue_rows, "your_clues": your_clue_rows})


@api_bp.get("/me/history")
@api_login_required
def history():
    user = current_user()

    guess_rows = []
    # History mirrors the playable catalog instead of showing soft-deleted
    # clues for spectrums that have been removed from SPECTRUMS.
    guesses = (
        Guess.query.join(Clue)
        .join(Spectrum)
        .filter(Guess.user_id == user.id, Clue.is_active.is_(True), Spectrum.is_active.is_(True))
        .order_by(Guess.created_at.desc())
        .limit(200)
        .all()
    )
    for guess in guesses:
        result = score_guess(guess)
        clue = guess.clue
        guess_rows.append(
            {
                "created_at": guess.created_at.isoformat(),
                "spectrum": clue.spectrum.label,
                **serialize_spectrum_poles(clue.spectrum),
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
    # Suppressed clues remain in the database for referential integrity, but
    # they are intentionally omitted from the player's visible clue history.
    clues = (
        Clue.query.join(Spectrum)
        .filter(Clue.author_user_id == user.id, Clue.is_active.is_(True), Spectrum.is_active.is_(True))
        .order_by(Clue.created_at.desc())
        .limit(200)
        .all()
    )
    for clue in clues:
        result = score_clue(clue)
        clue_rows.append(
            {
                "created_at": clue.created_at.isoformat(),
                "spectrum": clue.spectrum.label,
                **serialize_spectrum_poles(clue.spectrum),
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
            # Public stats count recoverable registered identities rather than
            # temporary guest rows, which can accumulate as people try the game.
            "users": User.query.filter(User.is_guest.is_(False)).count(),
            "spectrums": Spectrum.query.filter_by(is_active=True).count(),
            "clues": Clue.query.join(Spectrum).filter(Clue.is_active.is_(True), Spectrum.is_active.is_(True)).count(),
            "guesses": Guess.query.count(),
            "min_guesses_for_score": current_app.config["MIN_GUESSES_FOR_SCORE"],
        }
    )
