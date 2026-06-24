from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import hashlib
import hmac
import json
import math
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import cast, literal
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .models import Clue, Guess, Spectrum, User
from .moderation import normalize_username
from .session_helpers import current_user, get_csrf_token, is_admin_user, login_required, validate_csrf

web_bp = Blueprint("web", __name__)

MIN_PASSWORD_LENGTH = 8
SITE_BASE_URL = "https://wavelengthworld.app"
ACTIVITY_PAGE_SIZE = 50
PASSWORD_RESET_SALT = "wavelength-password-reset"
PASSWORD_RESET_COOLDOWN_SECONDS = 60


@web_bp.context_processor
def inject_globals():
    # Exposing only the boolean keeps templates from duplicating or weakening
    # the database-backed ADK authorization rule used by the Activity route.
    return {"csrf_token": get_csrf_token, "is_admin": is_admin_user(current_user())}


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


def password_reset_serializer() -> URLSafeTimedSerializer:
    # A dedicated salt prevents reset tokens from being accepted by any other
    # serializer that may also use the Flask SECRET_KEY elsewhere in the app.
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=PASSWORD_RESET_SALT)


def forgot_password_template(username: str = "", sent_email: str | None = None):
    # Keep the displayed lifetime synchronized with configuration so deployments
    # can adjust token expiry without leaving stale explanatory copy in the page.
    expiry_minutes = max(1, int(current_app.config["PASSWORD_RESET_MAX_AGE_SECONDS"]) // 60)
    return render_template(
        "forgot_password.html",
        username=username,
        sent_email=sent_email,
        reset_expiry_minutes=expiry_minutes,
    )


def password_hash_fingerprint(password_hash: str) -> str:
    # The signed payload contains only a one-way fingerprint of the stored hash.
    # Changing the password changes this value and invalidates every older link.
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()


def create_password_reset_token(user: User) -> str:
    if not user.password_hash:
        current_app.logger.error("Tried to create a password reset token for user %s without a password.", user.id)
        raise ValueError("User does not have a password.")
    return password_reset_serializer().dumps(
        {
            "user_id": user.id,
            "password_fingerprint": password_hash_fingerprint(user.password_hash),
        }
    )


def load_password_reset_user(token: str) -> tuple[User | None, str | None]:
    # SignatureExpired is handled separately so the page can explain whether the
    # link timed out or is simply malformed without exposing token internals.
    try:
        payload = password_reset_serializer().loads(
            token,
            max_age=int(current_app.config["PASSWORD_RESET_MAX_AGE_SECONDS"]),
        )
    except SignatureExpired:
        return None, "This password reset link has expired. Request a new one."
    except BadSignature:
        return None, "This password reset link is invalid. Request a new one."

    if not isinstance(payload, dict):
        current_app.logger.error("Password reset token decoded to an unexpected payload type.")
        return None, "This password reset link is invalid. Request a new one."

    user_id = payload.get("user_id")
    fingerprint = payload.get("password_fingerprint")
    if not isinstance(user_id, int) or not isinstance(fingerprint, str):
        current_app.logger.error("Password reset token decoded without the required fields.")
        return None, "This password reset link is invalid. Request a new one."

    user = User.query.get(user_id)
    if user is None or user.is_guest or not user.password_hash:
        return None, "This password reset link is no longer valid. Request a new one."

    current_fingerprint = password_hash_fingerprint(user.password_hash)
    if not hmac.compare_digest(fingerprint, current_fingerprint):
        return None, "This password reset link has already been used or replaced."
    return user, None


def mask_email(email: str) -> str:
    # The confirmation proves where the message was sent without echoing the full
    # recovery address to someone who only knows the account's username.
    local_part, separator, domain = email.partition("@")
    if not separator:
        current_app.logger.error("Stored recovery email for masking did not contain @.")
        return "the recovery email on this account"
    visible_local = local_part[:1]
    masked_local = visible_local + ("*" * max(3, len(local_part) - 1))
    return f"{masked_local}@{domain}"


def as_utc(value: datetime) -> datetime:
    # SQLite may return a naive datetime even for timezone-aware columns. Treat
    # those stored values as UTC so cooldown calculations behave consistently.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def send_password_reset_email(user: User, reset_url: str) -> bool:
    api_key = str(current_app.config.get("RESEND_API_KEY", "")).strip()
    from_email = str(current_app.config.get("RESEND_FROM_EMAIL", "")).strip()
    if not api_key or not from_email:
        current_app.logger.error("Password reset email requested but Resend is not configured.")
        return False
    if not user.email:
        current_app.logger.error("Password reset email send reached user %s without a recovery email.", user.id)
        return False

    # Both message formats contain the same short-lived link. User-controlled
    # values are escaped before entering HTML, and neither tokens nor URLs are
    # written to logs if the provider request fails.
    username_html = escape(user.username_display)
    reset_url_html = escape(reset_url, quote=True)
    max_age_minutes = max(1, int(current_app.config["PASSWORD_RESET_MAX_AGE_SECONDS"]) // 60)
    payload = {
        "from": from_email,
        "to": [user.email],
        "subject": "Reset your Wavelength World password",
        "text": (
            f"Hi {user.username_display},\n\n"
            f"Use this link to reset your Wavelength World password:\n{reset_url}\n\n"
            f"This link expires in {max_age_minutes} minutes. If you did not request it, you can ignore this email."
        ),
        "html": (
            f"<p>Hi {username_html},</p>"
            f"<p><a href=\"{reset_url_html}\">Reset your Wavelength World password</a>.</p>"
            f"<p>This link expires in {max_age_minutes} minutes. "
            "If you did not request it, you can ignore this email.</p>"
        ),
    }
    resend_request = Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(resend_request, timeout=10) as response:
            if response.status < 200 or response.status >= 300:
                current_app.logger.error("Resend returned unexpected status %s for password recovery.", response.status)
                return False
    except HTTPError as error:
        current_app.logger.error("Resend rejected a password recovery email with status %s.", error.code)
        return False
    except (URLError, TimeoutError, OSError) as error:
        current_app.logger.error("Password recovery email delivery failed: %s.", type(error).__name__)
        return False
    return True


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
    return render_template("index.html")


@web_bp.get("/login")
def login_page():
    if current_user() is not None:
        return redirect(url_for("web.play"))
    return login_template()


@web_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return forgot_password_template(username=request.args.get("username", "").strip())

    username_display = request.form.get("username", "").strip()
    username_normalized, error = validate_username(username_display)
    if error:
        flash(error, "error")
        return forgot_password_template(username=username_display)

    user = User.query.filter_by(username_normalized=username_normalized).first()
    if user is None:
        flash("No account was found with that username.", "error")
        return forgot_password_template(username=username_display)
    if user.is_guest or not user.email:
        flash(
            "This account does not have a recovery email, so its password cannot be recovered.",
            "error",
        )
        return forgot_password_template(username=user.username_display)
    if not user.password_hash:
        flash("This account has not set a password yet. Return to login to create one.", "error")
        return forgot_password_template(username=user.username_display)

    now = datetime.now(timezone.utc)
    if user.password_reset_sent_at is not None:
        seconds_since_send = (now - as_utc(user.password_reset_sent_at)).total_seconds()
        if seconds_since_send < PASSWORD_RESET_COOLDOWN_SECONDS:
            return forgot_password_template(
                username=user.username_display,
                sent_email=mask_email(user.email),
            )

    try:
        token = create_password_reset_token(user)
    except ValueError:
        flash("This account cannot reset its password. Return to login and try again.", "error")
        return forgot_password_template(username=user.username_display)

    reset_path = url_for("web.reset_password", token=token)
    reset_url = f"{current_app.config['SITE_BASE_URL']}{reset_path}"
    if not send_password_reset_email(user, reset_url):
        flash("The reset email could not be sent right now. Please try again later.", "error")
        return forgot_password_template(username=user.username_display)

    user.password_reset_sent_at = now
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        # The email was already accepted by Resend, so the player should still
        # receive a success response. Logging preserves visibility into the lost
        # cooldown timestamp without leaking the reset link.
        current_app.logger.error("Could not store password reset send time for user %s.", user.id)

    return forgot_password_template(
        username=user.username_display,
        sent_email=mask_email(user.email),
    )


@web_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    user, token_error = load_password_reset_user(token)
    if token_error:
        return render_template("reset_password.html", token_valid=False, token_error=token_error, token=token)
    if user is None:
        current_app.logger.error("Password reset token validation returned no user and no error.")
        return render_template(
            "reset_password.html",
            token_valid=False,
            token_error="This password reset link is invalid. Request a new one.",
            token=token,
        )

    if request.method == "GET":
        return render_template(
            "reset_password.html",
            token_valid=True,
            token_error=None,
            token=token,
            username=user.username_display,
        )

    password = request.form.get("password", "")
    password_confirm = request.form.get("password_confirm", "")
    password_error = validate_password_pair(password, password_confirm)
    if password_error:
        flash(password_error, "error")
        return render_template(
            "reset_password.html",
            token_valid=True,
            token_error=None,
            token=token,
            username=user.username_display,
        )

    now = datetime.now(timezone.utc)
    user.password_hash = generate_password_hash(password)
    user.password_set_at = now
    user.password_reset_sent_at = None
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.error("Could not persist a password reset for user %s.", user.id)
        flash("Your password could not be reset right now. Please try again.", "error")
        return render_template(
            "reset_password.html",
            token_valid=True,
            token_error=None,
            token=token,
            username=user.username_display,
        )

    # A reset link may be opened while another account is logged in on the same
    # browser. Clearing the session avoids leaving that unrelated identity active.
    session.clear()
    flash("Your password has been reset. Log in with your new password.", "success")
    return redirect(url_for("web.login_page"))


@web_bp.get("/how-to-play")
def how_to_play():
    return render_template("how_to_play.html")


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


@web_bp.get("/robots.txt")
def robots_txt():
    content = "\n".join(
        [
            "User-agent: *",
            "Allow: /",
            "Disallow: /play",
            "Disallow: /friends",
            "Disallow: /activity",
            "Disallow: /api",
            "Disallow: /login",
            "Disallow: /forgot-password",
            "Disallow: /reset-password",
            f"Sitemap: {SITE_BASE_URL}/sitemap.xml",
            "",
        ]
    )
    return current_app.response_class(content, mimetype="text/plain")


@web_bp.get("/sitemap.xml")
def sitemap_xml():
    content = "\n".join(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
            "  <url>",
            f"    <loc>{SITE_BASE_URL}/</loc>",
            "  </url>",
            "  <url>",
            f"    <loc>{SITE_BASE_URL}/how-to-play</loc>",
            "  </url>",
            "</urlset>",
            "",
        ]
    )
    return current_app.response_class(content, mimetype="application/xml")


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


def activity_query():
    # Guesses and player-created clues live in separate tables, so the Activity
    # feed projects them into one shared row shape before sorting and paginating.
    # Outer joins deliberately preserve damaged historical rows long enough for
    # the renderer to report their missing relationships instead of silently
    # dropping activity from the admin audit view.
    guess_activity = (
        db.session.query(
            Guess.id.label("record_id"),
            literal("guess").label("activity_type"),
            Guess.created_at.label("created_at"),
            User.id.label("user_id"),
            User.username_display.label("username"),
            User.is_guest.label("is_guest"),
            Clue.id.label("clue_id"),
            Spectrum.id.label("spectrum_id"),
            Spectrum.left_label.label("spectrum_left_label"),
            Spectrum.right_label.label("spectrum_right_label"),
            Clue.text.label("clue_text"),
            Guess.personal_position.label("personal_position"),
            Guess.predicted_average_position.label("predicted_average_position"),
            cast(literal(None), db.Float).label("target_position"),
        )
        .select_from(Guess)
        .outerjoin(User, Guess.user_id == User.id)
        .outerjoin(Clue, Guess.clue_id == Clue.id)
        .outerjoin(Spectrum, Clue.spectrum_id == Spectrum.id)
    )
    clue_activity = (
        db.session.query(
            Clue.id.label("record_id"),
            literal("clue").label("activity_type"),
            Clue.created_at.label("created_at"),
            User.id.label("user_id"),
            User.username_display.label("username"),
            User.is_guest.label("is_guest"),
            Clue.id.label("clue_id"),
            Spectrum.id.label("spectrum_id"),
            Spectrum.left_label.label("spectrum_left_label"),
            Spectrum.right_label.label("spectrum_right_label"),
            Clue.text.label("clue_text"),
            cast(literal(None), db.Float).label("personal_position"),
            cast(literal(None), db.Float).label("predicted_average_position"),
            Clue.target_position.label("target_position"),
        )
        .select_from(Clue)
        .outerjoin(User, Clue.author_user_id == User.id)
        .outerjoin(Spectrum, Clue.spectrum_id == Spectrum.id)
        .filter(Clue.is_seed.is_(False))
    )
    return guess_activity.union_all(clue_activity).subquery()


def serialize_activity_row(row) -> dict:
    # Foreign keys should make every relationship below available. If historical
    # data is ever damaged or imported without constraints, keep the row visible
    # with an explicit fallback and emit an error that can be investigated.
    if row.user_id is None or not row.username:
        current_app.logger.error(
            "Activity %s %s points at a missing user.",
            row.activity_type,
            row.record_id,
        )
    if row.clue_id is None or row.clue_text is None:
        current_app.logger.error(
            "Activity %s %s points at a missing clue.",
            row.activity_type,
            row.record_id,
        )
    if row.spectrum_id is None or row.spectrum_left_label is None or row.spectrum_right_label is None:
        current_app.logger.error(
            "Activity %s %s points at a missing spectrum.",
            row.activity_type,
            row.record_id,
        )
    if row.created_at is None:
        current_app.logger.error(
            "Activity %s %s has no creation timestamp.",
            row.activity_type,
            row.record_id,
        )

    created_at = row.created_at
    if created_at is not None and created_at.tzinfo is None:
        # SQLite returns timezone-aware columns as naive datetime objects even
        # though this app stores UTC. Reattaching UTC before creating the ISO
        # value prevents browsers from misreading the stored value as local time.
        created_at = created_at.replace(tzinfo=timezone.utc)

    return {
        "record_id": row.record_id,
        "activity_type": row.activity_type,
        "created_at_iso": created_at.isoformat() if created_at is not None else "",
        "username": row.username or f"Missing user ({row.user_id or 'unknown id'})",
        "is_guest": bool(row.is_guest),
        "spectrum_left_label": row.spectrum_left_label or "Missing spectrum",
        "spectrum_right_label": row.spectrum_right_label or "Missing spectrum",
        "clue_text": row.clue_text or "Missing clue",
        "personal_position": row.personal_position,
        "predicted_average_position": row.predicted_average_position,
        "target_position": row.target_position,
    }


@web_bp.get("/activity")
@login_required
def activity():
    user = current_user()
    if user is None:
        current_app.logger.error("login_required allowed a missing user into the Activity page.")
        abort(403)
    if not is_admin_user(user):
        abort(403)

    activity = activity_query()
    # Filtering happens before counting and paginating so each tab has its own
    # accurate total and page range. Unknown query-string values safely fall
    # back to the complete feed rather than producing an empty or broken view.
    activity_type = request.args.get("type", "all").lower()
    if activity_type not in {"all", "clue", "guess"}:
        activity_type = "all"

    filtered_activity = db.session.query(activity)
    if activity_type != "all":
        filtered_activity = filtered_activity.filter(activity.c.activity_type == activity_type)

    total_rows = filtered_activity.count()
    page_count = max(1, math.ceil(total_rows / ACTIVITY_PAGE_SIZE))

    # Flask returns None for absent and non-integer typed query parameters. Both
    # those cases, zero, and negative values normalize to the first page, while
    # values beyond the end normalize to the final available page.
    requested_page = request.args.get("page", type=int)
    page = min(max(requested_page or 1, 1), page_count)

    # IDs are unique only within their source table, so activity type provides a
    # final stable tie-breaker after the requested timestamp-descending and
    # record-ID-descending ordering.
    rows = (
        filtered_activity
        .order_by(
            activity.c.created_at.desc(),
            activity.c.record_id.desc(),
            activity.c.activity_type.asc(),
        )
        .offset((page - 1) * ACTIVITY_PAGE_SIZE)
        .limit(ACTIVITY_PAGE_SIZE)
        .all()
    )

    return render_template(
        "activity.html",
        activity_rows=[serialize_activity_row(row) for row in rows],
        page=page,
        page_count=page_count,
        total_rows=total_rows,
        activity_type=activity_type,
    )
