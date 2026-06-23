from __future__ import annotations

import random

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from . import db
from .models import Clue, CluerTask, Guess, PromptView, Spectrum, User


def serialize_spectrum(spectrum: Spectrum) -> dict:
    return {
        "id": spectrum.id,
        "left_label": spectrum.left_label,
        "right_label": spectrum.right_label,
        "category": spectrum.category,
        "difficulty": spectrum.difficulty,
    }


def get_guesser_prompt(user: User) -> dict | None:
    guessed_subquery = db.session.query(Guess.clue_id).filter(Guess.user_id == user.id)
    viewed_subquery = db.session.query(PromptView.clue_id).filter(
        PromptView.user_id == user.id,
        PromptView.prompt_type == "guesser",
        PromptView.clue_id.isnot(None),
    )

    # A skipped Guesser prompt is still a valid future prompt because the player
    # has not actually guessed it yet. The first pass protects the immediate
    # Play Another flow from repeating recently skipped clues while fresh clues
    # remain; the fallback pass intentionally lets skipped clues return after
    # every never-seen eligible clue has been offered.
    base_query = Clue.query.join(Spectrum).filter(
        Clue.is_active.is_(True),
        Spectrum.is_active.is_(True),
        ~Clue.id.in_(guessed_subquery),
        or_(Clue.author_user_id.is_(None), Clue.author_user_id != user.id),
    )
    is_recycled_view = False
    clue = base_query.filter(~Clue.id.in_(viewed_subquery)).order_by(func.random()).first()
    if clue is None:
        is_recycled_view = True
        clue = base_query.order_by(func.random()).first()

    if clue is None:
        return None

    # Mark new prompts as seen so Play Again can exhaust fresh prompts before
    # recycling skipped ones. Recycled prompts already have a PromptView row, so
    # they do not need another write when they come back around.
    if not is_recycled_view:
        db.session.add(PromptView(user_id=user.id, prompt_type="guesser", clue_id=clue.id))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()

    return {
        "clue_id": clue.id,
        "spectrum": serialize_spectrum(clue.spectrum),
        "clue_text": clue.text,
    }


def create_cluer_prompt(user: User) -> dict | None:
    spectrum = Spectrum.query.filter_by(is_active=True).order_by(func.random()).first()
    if spectrum is None:
        return None

    task = CluerTask(
        user_id=user.id,
        spectrum_id=spectrum.id,
        target_position=random.uniform(0.0, 100.0),
    )
    db.session.add(task)
    db.session.commit()

    return {
        "task_id": task.id,
        "spectrum": serialize_spectrum(spectrum),
        "target_position": round(task.target_position, 2),
    }
