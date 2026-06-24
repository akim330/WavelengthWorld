import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
INSTANCE_DIR.mkdir(exist_ok=True)


def _local_database_url():
    """Return the SQLite URL used when no deployment database is configured."""
    return f"sqlite:///{INSTANCE_DIR / 'wavelength.sqlite3'}"


def _database_url_from_environment():
    """
    Return a SQLAlchemy database URL that is safe for local and hosted startup.

    Hosted environments such as Render usually provide DATABASE_URL directly, but
    it is easy to accidentally configure the variable as an empty string, wrap the
    copied URL in quotes, or paste the whole ``DATABASE_URL=...`` assignment as the
    value. Normalizing those cases here keeps local startup on SQLite and gives a
    clear error for values that still are not complete SQLAlchemy URLs.
    """
    raw_database_url = os.environ.get("DATABASE_URL")

    # A missing or blank DATABASE_URL should behave like local development and use
    # the project SQLite file. Without this check, an empty environment variable is
    # passed to SQLAlchemy and startup fails with a vague URL parse error.
    if raw_database_url is None or not raw_database_url.strip():
        return _local_database_url()

    # Strip shell-style quotes before and after removing an accidental variable
    # name prefix so values like ``"DATABASE_URL=postgres://..."`` are normalized
    # the same way as unquoted dashboard values.
    database_url = raw_database_url.strip().strip("\"'").strip()

    # If the Render environment variable value was pasted as ``DATABASE_URL=...``
    # instead of only the URL, remove the accidental key prefix before validation.
    if database_url.startswith("DATABASE_URL="):
        database_url = database_url.split("=", 1)[1].strip().strip("\"'").strip()

    # Environment dashboards sometimes preserve surrounding quotes from copied
    # shell syntax. SQLAlchemy expects the URL itself, so strip only outer quotes.
    database_url = database_url.strip("\"'").strip()

    if not database_url:
        return _local_database_url()

    # Some hosted Postgres providers still expose the legacy postgres:// scheme.
    # SQLAlchemy's Postgres dialect is named postgresql://, so normalize before the
    # URL reaches Flask-SQLAlchemy.
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    # Raise a focused configuration error before Flask-SQLAlchemy emits the more
    # generic "Could not parse SQLAlchemy URL" traceback.
    if "://" not in database_url:
        raise RuntimeError(
            "DATABASE_URL must be a full SQLAlchemy URL, such as "
            "postgresql://user:password@host:port/database or sqlite:///path/to/db."
        )

    return database_url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
    SQLALCHEMY_DATABASE_URI = _database_url_from_environment()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Every clue's original target is treated as the first opinion in its
    # evolving average. Requiring two total opinions therefore lets the first
    # player response produce a score immediately.
    MIN_OPINIONS_FOR_SCORE = 2
    DAILY_LEADERBOARD_MIN_ENTRIES = 0
    WEEKLY_LEADERBOARD_MIN_ENTRIES = 5
    ALL_TIME_LEADERBOARD_MIN_ENTRIES = 10
    # Backward-compatibility alias for older code paths still reading "lifetime".
    LIFETIME_LEADERBOARD_MIN_ENTRIES = ALL_TIME_LEADERBOARD_MIN_ENTRIES

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
