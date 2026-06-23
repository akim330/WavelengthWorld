from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from config import Config


db = SQLAlchemy()


def ensure_user_settings_columns():
    inspector = inspect(db.engine)
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "show_on_leaderboards" in user_columns:
        return

    # create_all() does not alter existing tables, so this small additive schema
    # sync keeps the leaderboard visibility preference available for current
    # local databases without introducing a full migration framework.
    with db.engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN show_on_leaderboards BOOLEAN NOT NULL DEFAULT TRUE"))


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
        ensure_user_settings_columns()
        seed_if_empty()

    return app
