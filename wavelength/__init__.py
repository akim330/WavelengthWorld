from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from config import Config


db = SQLAlchemy()


def ensure_user_columns():
    inspector = inspect(db.engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}

    # create_all() does not alter existing tables, so this small additive schema
    # sync keeps newly-added user account fields available for current local and
    # hosted databases without introducing a full migration framework.
    with db.engine.begin() as connection:
        if "show_on_leaderboards" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN show_on_leaderboards BOOLEAN NOT NULL DEFAULT TRUE"))
        if "password_hash" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)"))
        if "email" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
        if "email_normalized" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN email_normalized VARCHAR(255)"))
        if "is_guest" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN is_guest BOOLEAN NOT NULL DEFAULT FALSE"))
        if "password_set_at" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN password_set_at TIMESTAMP"))
        if "password_reset_sent_at" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN password_reset_sent_at TIMESTAMP"))

        # Existing databases cannot receive the model-level unique constraint via
        # create_all(), so create the same nullable unique lookup index manually.
        # Both SQLite and PostgreSQL allow many NULL values in a unique index,
        # which keeps optional recovery email truly optional.
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_normalized ON users (email_normalized)"))


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    db.init_app(app)

    from .routes import web_bp
    from .api import api_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp, url_prefix="/api")

    with app.app_context():
        from . import models  # noqa: F401
        from .seed import seed_if_empty

        db.create_all()
        ensure_user_columns()
        seed_if_empty()

    return app
