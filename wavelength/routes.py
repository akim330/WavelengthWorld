from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from . import db
from .models import User
from .moderation import normalize_username
from .session_helpers import current_user, get_csrf_token, login_required

web_bp = Blueprint("web", __name__)


@web_bp.context_processor
def inject_globals():
    return {"csrf_token": get_csrf_token}


@web_bp.get("/")
def index():
    if current_user() is not None:
        return redirect(url_for("web.play"))
    return render_template("login.html")


@web_bp.post("/login")
def login():
    username_display = request.form.get("username", "").strip()
    username_normalized = normalize_username(username_display)

    if not username_normalized:
        flash("Please enter a username.", "error")
        return redirect(url_for("web.index"))

    if len(username_normalized) > 80:
        flash("Username is too long.", "error")
        return redirect(url_for("web.index"))

    user = User.query.filter_by(username_normalized=username_normalized).first()
    if user is None:
        user = User(
            username_display=username_display,
            username_normalized=username_normalized,
            last_seen_at=datetime.now(timezone.utc),
        )
        db.session.add(user)
    else:
        user.username_display = username_display or user.username_display
        user.last_seen_at = datetime.now(timezone.utc)

    db.session.commit()
    session["user_id"] = user.id
    session["username"] = user.username_display
    get_csrf_token()
    return redirect(url_for("web.play"))


@web_bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.index"))


@web_bp.get("/play")
@login_required
def play():
    return render_template("play.html")
