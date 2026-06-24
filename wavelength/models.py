from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint, Index, CheckConstraint

from . import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username_display = db.Column(db.String(80), nullable=False)
    username_normalized = db.Column(db.String(80), nullable=False, unique=True, index=True)
    # Password hashes stay nullable so existing passwordless accounts can be
    # claimed on their first return and guest accounts can remain intentionally
    # unrecoverable. The app should never store or compare raw passwords.
    password_hash = db.Column(db.String(255), nullable=True)
    # Recovery email is optional in this lightweight auth pass. The display
    # value preserves the player's spelling, while email_normalized supports
    # case-insensitive duplicate checks and future recovery lookup.
    email = db.Column(db.String(255), nullable=True)
    email_normalized = db.Column(db.String(255), nullable=True, unique=True, index=True)
    # Guest rows are persisted only so their in-session guesses and clues can
    # keep normal foreign keys. They are hidden from social and public identity
    # features because the player cannot log back into them later.
    is_guest = db.Column(db.Boolean, nullable=False, default=False)
    # Tracking when a password was first attached lets the login flow distinguish
    # legacy passwordless users from normal password-authenticated users.
    password_set_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # The most recent successful reset-email send time enforces a small per-user
    # cooldown without storing reset tokens or introducing a separate token table.
    password_reset_sent_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    # Players may still submit guesses and clues while hidden from public
    # leaderboards. Keeping the preference on the user lets both guesser and
    # cluer leaderboard queries apply the same privacy choice consistently.
    show_on_leaderboards = db.Column(db.Boolean, nullable=False, default=True)

    clues = db.relationship("Clue", back_populates="author", lazy=True)
    guesses = db.relationship("Guess", back_populates="user", lazy=True)
    sent_friend_requests = db.relationship(
        "FriendRequest",
        foreign_keys="FriendRequest.requester_user_id",
        back_populates="requester",
        lazy=True,
    )
    received_friend_requests = db.relationship(
        "FriendRequest",
        foreign_keys="FriendRequest.addressee_user_id",
        back_populates="addressee",
        lazy=True,
    )


class FriendRequest(db.Model):
    __tablename__ = "friend_requests"
    __table_args__ = (
        Index("ix_friend_requests_addressee_status", "addressee_user_id", "status"),
        Index("ix_friend_requests_requester_status", "requester_user_id", "status"),
    )

    id = db.Column(db.Integer, primary_key=True)
    requester_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    addressee_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    # Requests preserve direction so the UI can distinguish sent requests from
    # requests that need the current player's response.
    requester = db.relationship("User", foreign_keys=[requester_user_id], back_populates="sent_friend_requests")
    addressee = db.relationship("User", foreign_keys=[addressee_user_id], back_populates="received_friend_requests")


class Friendship(db.Model):
    __tablename__ = "friendships"
    __table_args__ = (
        UniqueConstraint("user_low_id", "user_high_id", name="uq_friendship_pair"),
        CheckConstraint("user_low_id < user_high_id", name="ck_friendship_ordered_pair"),
        Index("ix_friendships_low", "user_low_id"),
        Index("ix_friendships_high", "user_high_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_low_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user_high_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    # Storing the smaller user id first makes one row represent both directions
    # of the friendship without needing duplicate reverse rows.
    user_low = db.relationship("User", foreign_keys=[user_low_id])
    user_high = db.relationship("User", foreign_keys=[user_high_id])


class Spectrum(db.Model):
    __tablename__ = "spectrums"

    id = db.Column(db.Integer, primary_key=True)
    left_label = db.Column(db.String(120), nullable=False)
    right_label = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(80), nullable=False, default="General")
    difficulty = db.Column(db.String(30), nullable=False, default="medium")
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    clues = db.relationship("Clue", back_populates="spectrum", lazy=True)

    @property
    def label(self) -> str:
        return f"{self.left_label} / {self.right_label}"


class Clue(db.Model):
    __tablename__ = "clues"
    __table_args__ = (
        UniqueConstraint("spectrum_id", "normalized_text", name="uq_clue_spectrum_normalized_text"),
        Index("ix_clues_active_created", "is_active", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    spectrum_id = db.Column(db.Integer, db.ForeignKey("spectrums.id"), nullable=False, index=True)
    author_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    text = db.Column(db.Text, nullable=False)
    normalized_text = db.Column(db.Text, nullable=False)
    target_position = db.Column(db.Float, nullable=False)
    is_seed = db.Column(db.Boolean, nullable=False, default=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    spectrum = db.relationship("Spectrum", back_populates="clues")
    author = db.relationship("User", back_populates="clues")
    guesses = db.relationship("Guess", back_populates="clue", lazy=True, cascade="all, delete-orphan")


class Guess(db.Model):
    __tablename__ = "guesses"
    __table_args__ = (
        UniqueConstraint("clue_id", "user_id", name="uq_guess_clue_user"),
        Index("ix_guesses_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    clue_id = db.Column(db.Integer, db.ForeignKey("clues.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    personal_position = db.Column(db.Float, nullable=False)
    predicted_average_position = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    clue = db.relationship("Clue", back_populates="guesses")
    user = db.relationship("User", back_populates="guesses")


class CluerTask(db.Model):
    __tablename__ = "cluer_tasks"
    __table_args__ = (
        Index("ix_cluer_tasks_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    spectrum_id = db.Column(db.Integer, db.ForeignKey("spectrums.id"), nullable=False, index=True)
    target_position = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_clue_id = db.Column(db.Integer, db.ForeignKey("clues.id"), nullable=True)

    user = db.relationship("User")
    spectrum = db.relationship("Spectrum")
    created_clue = db.relationship("Clue", foreign_keys=[created_clue_id])


class PromptView(db.Model):
    __tablename__ = "prompt_views"
    __table_args__ = (
        UniqueConstraint("user_id", "prompt_type", "clue_id", name="uq_prompt_view_user_type_clue"),
        Index("ix_prompt_views_user_created", "user_id", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    prompt_type = db.Column(db.String(30), nullable=False, index=True)
    clue_id = db.Column(db.Integer, db.ForeignKey("clues.id"), nullable=True, index=True)
    cluer_task_id = db.Column(db.Integer, db.ForeignKey("cluer_tasks.id"), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    user = db.relationship("User")
    clue = db.relationship("Clue")
    cluer_task = db.relationship("CluerTask")
