import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{INSTANCE_DIR / 'wavelength.sqlite3'}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MIN_GUESSES_FOR_SCORE = 3
    DAILY_LEADERBOARD_MIN_ENTRIES = 3
    LIFETIME_LEADERBOARD_MIN_ENTRIES = 10

    # Distances are on a 0-100 dial scale.
    SCORING_BANDS = [
        (2.5, 4),
        (7.5, 3),
        (12.5, 2),
        (17.5, 1),
    ]

    DIAL_MIN = 0.0
    DIAL_MAX = 100.0
    DAILY_SCORE_MODE = "submitted_today"
