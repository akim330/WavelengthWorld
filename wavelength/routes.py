from __future__ import annotations

from datetime import datetime, timezone
import secrets

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .models import User
from .moderation import normalize_username
from .session_helpers import current_user, get_csrf_token, login_required, validate_csrf

web_bp = Blueprint("web", __name__)

MIN_PASSWORD_LENGTH = 8


@web_bp.context_processor
def inject_globals():
    return {"csrf_token": get_csrf_token}


@web_bp.before_request
def csrf_guard():
    if validate_csrf():
        return None
    flash("Refresh the page and try again.", "error")
    return redirect(url_for("web.index"))


def login_template(mode: str = "lookup", username: str = "", email: str = ""):
    # The login page is intentionally server-rendered as a small state machine so
    # every auth branch can reuse the same CSRF handling, flash messages, and
    # visual layout without requiring client-side account discovery.
    return render_template("login.html", mode=mode, username=username, email=email)


def validate_username(username_display: str) -> tuple[str | None, str | None]:
    # Usernames remain normalized exactly like the old passwordless flow so
    # existing score history stays attached to the same case-insensitive account.
    username_normalized = normalize_username(username_display)
    if not username_normalized:
        return None, "Please enter a username."
    if len(username_normalized) > 80:
        return None, "Username is too long."
    return username_normalized, None


def validate_password_pair(password: str, password_confirm: str) -> str | None:
    # Password validation is deliberately small for this lightweight login
    # system: long enough to avoid empty/throwaway passwords, but not a full
    # production policy that would make the prototype annoying to use.
    if not password:
        return "Please enter a password."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password != password_confirm:
        return "Passwords do not match."
    return None


def normalize_optional_email(email_display: str) -> tuple[str | None, str | None, str | None]:
    # Email is stored only for future/manual recovery, so the validation is just
    # enough to avoid obviously unusable values while keeping the field optional.
    email = email_display.strip()
    if not email:
        return None, None, None
    if email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        return email, None, "Enter a valid email address or leave it blank."
    return email, email.lower(), None


def email_belongs_to_another_user(email_normalized: str | None, user: User | None = None) -> bool:
    if not email_normalized:
        return False
    query = User.query.filter_by(email_normalized=email_normalized)
    if user is not None:
        query = query.filter(User.id != user.id)
    return query.first() is not None


def sign_in_user(user: User):
    # Centralizing session setup keeps registered users, claimed legacy users,
    # and guests on the same session contract used by the rest of the app.
    session.clear()
    session["user_id"] = user.id
    session["username"] = user.username_display
    session["is_guest"] = user.is_guest
    get_csrf_token()


@web_bp.get("/")
def index():
    if current_user() is not None:
        return redirect(url_for("web.play"))
    return login_template()


@web_bp.post("/login")
def login():
    action = request.form.get("action", "lookup")

    if action == "guest":
        return create_guest_session()
    if action == "lookup":
        return lookup_username()
    if action == "login":
        return login_with_password()
    if action == "register":
        return register_user()
    if action == "claim":
        return claim_legacy_user()

    current_app.logger.error("Unknown login action %s.", action)
    flash("Something went wrong. Refresh the page and try again.", "error")
    return redirect(url_for("web.index"))


def lookup_username():
    username_display = request.form.get("username", "").strip()
    username_normalized, error = validate_username(username_display)

    if error:
        flash(error, "error")
        return login_template(username=username_display)

    user = User.query.filter_by(username_normalized=username_normalized).first()
    if user is None:
        return login_template(mode="register", username=username_display)
    if user.is_guest:
        current_app.logger.error("Guest account %s was reached through username login.", user.id)
        flash("That guest account cannot be logged into. Create an account or play as a new guest.", "error")
        return login_template(username=username_display)
    if user.password_hash:
        return login_template(mode="login", username=user.username_display)
    return login_template(mode="claim", username=user.username_display)


def login_with_password():
    username_display = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    username_normalized, error = validate_username(username_display)

    if error:
        flash(error, "error")
        return login_template(username=username_display)

    user = User.query.filter_by(username_normalized=username_normalized).first()
    if user is None:
        return login_template(mode="register", username=username_display)
    if user.is_guest:
        current_app.logger.error("Guest account %s was reached through password login.", user.id)
        flash("That guest account cannot be logged into. Create an account or play as a new guest.", "error")
        return login_template(username=username_display)
    if not user.password_hash:
        return login_template(mode="claim", username=user.username_display)
    if not check_password_hash(user.password_hash, password):
        flash("Password is incorrect.", "error")
        return login_template(mode="login", username=user.username_display)

    user.username_display = username_display or user.username_display
    user.last_seen_at = datetime.now(timezone.utc)
    db.session.commit()
    sign_in_user(user)
    return redirect(url_for("web.play"))


def register_user():
    username_display = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")
    email_display = request.form.get("email", "")
    username_normalized, username_error = validate_username(username_display)
    email, email_normalized, email_error = normalize_optional_email(email_display)
    password_error = validate_password_pair(password, password_confirm)

    if username_error or password_error or email_error:
        flash(username_error or password_error or email_error, "error")
        return login_template(mode="register", username=username_display, email=email_display)
    if email_belongs_to_another_user(email_normalized):
        flash("That recovery email is already attached to another account.", "error")
        return login_template(mode="register", username=username_display, email=email_display)

    existing_user = User.query.filter_by(username_normalized=username_normalized).first()
    if existing_user is not None:
        if existing_user.is_guest:
            current_app.logger.error("Registration collided with guest account %s.", existing_user.id)
            flash("That username is not available. Try another username.", "error")
            return login_template(mode="register", username=username_display, email=email_display)
        flash("That username already exists. Continue with that account instead.", "error")
        if existing_user.password_hash:
            return login_template(mode="login", username=existing_user.username_display)
        return login_template(mode="claim", username=existing_user.username_display, email=email_display)

    now = datetime.now(timezone.utc)
    user = User(
        username_display=username_display,
        username_normalized=username_normalized,
        password_hash=generate_password_hash(password),
        email=email,
        email_normalized=email_normalized,
        password_set_at=now,
        last_seen_at=now,
    )
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("That username or recovery email is already in use.", "error")
        return login_template(mode="register", username=username_display, email=email_display)

    sign_in_user(user)
    return redirect(url_for("web.play"))


def claim_legacy_user():
    username_display = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")
    email_display = request.form.get("email", "")
    username_normalized, username_error = validate_username(username_display)
    email, email_normalized, email_error = normalize_optional_email(email_display)
    password_error = validate_password_pair(password, password_confirm)

    if username_error or password_error or email_error:
        flash(username_error or password_error or email_error, "error")
        return login_template(mode="claim", username=username_display, email=email_display)
    user = User.query.filter_by(username_normalized=username_normalized).first()
    if user is None:
        return login_template(mode="register", username=username_display, email=email_display)
    if user.is_guest:
        current_app.logger.error("Guest account %s was reached through legacy claim.", user.id)
        flash("That guest account cannot be claimed. Create an account or play as a new guest.", "error")
        return login_template(username=username_display)
    if user.password_hash:
        flash("That account already has a password. Log in instead.", "error")
        return login_template(mode="login", username=user.username_display)
    if email_belongs_to_another_user(email_normalized, user):
        flash("That recovery email is already attached to another account.", "error")
        return login_template(mode="claim", username=username_display, email=email_display)

    now = datetime.now(timezone.utc)
    user.username_display = username_display or user.username_display
    user.password_hash = generate_password_hash(password)
    user.email = email
    user.email_normalized = email_normalized
    user.password_set_at = now
    user.last_seen_at = now

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("That recovery email is already in use.", "error")
        return login_template(mode="claim", username=username_display, email=email_display)

    sign_in_user(user)
    return redirect(url_for("web.play"))


def create_guest_session():
    now = datetime.now(timezone.utc)
    for _ in range(8):
        token = secrets.token_hex(4)
        username_display = f"Guest {token}"
        username_normalized = normalize_username(username_display)
        if User.query.filter_by(username_normalized=username_normalized).first() is not None:
            continue

        # Guest users intentionally get no password or email. Their database row
        # lets normal gameplay records keep working during this browser session,
        # while show_on_leaderboards=False keeps the temporary identity private.
        user = User(
            username_display=username_display,
            username_normalized=username_normalized,
            is_guest=True,
            show_on_leaderboards=False,
            last_seen_at=now,
        )
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            continue

        sign_in_user(user)
        return redirect(url_for("web.play"))

    current_app.logger.error("Could not create a unique guest account after repeated attempts.")
    flash("Could not start a guest session. Please try again.", "error")
    return redirect(url_for("web.index"))


@web_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.index"))


@web_bp.get("/play")
@login_required
def play():
    return render_template("play.html")


@web_bp.get("/friends")
@login_required
def friends():
    user = current_user()
    if user is None:
        current_app.logger.error("login_required allowed a missing user into the friends page.")
        return redirect(url_for("web.index"))
    if user.is_guest:
        flash("Guests cannot use friends. Create an account if you want social features.", "error")
        return redirect(url_for("web.play"))
    return render_template("friends.html")
