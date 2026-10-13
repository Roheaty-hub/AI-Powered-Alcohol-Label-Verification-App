"""Flask application factory."""
from __future__ import annotations

import os

from flask import Flask

from app.routes import bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Generous cap so a 300-label batch fits; single images are limited separately.
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("MAX_UPLOAD_MB", "300")) * 1024 * 1024
    app.register_blueprint(bp)
    return app
