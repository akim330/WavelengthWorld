from __future__ import annotations

import secrets
from functools import wraps
from typing import Callable, TypeVar

from flask import jsonify, redirect, request, session, url_for

from .models import User

F = TypeVar("F", bound=Callable)


def current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = User.query.get(user_id)
    if user is None:
        session.pop("user_id", None)
        session.pop("username", None)
        return None
    return user


def login_required(view: F) -> F:
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("web.index"))
        return view(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def api_login_required(view: F) -> F:
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return jsonify({"error": "login_required"}), 401
        return view(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def get_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf() -> bool:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return True
    sent = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
    return bool(sent and sent == session.get("csrf_token"))
