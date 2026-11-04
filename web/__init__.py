from flask import Flask, jsonify

from config import BASE_DIR, SECRET_KEY
from services import db


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.secret_key = SECRET_KEY
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    db.init_db()

    @app.errorhandler(413)
    def file_too_large(_error):
        return jsonify({"error": "File is too large (max 10 MB)."}), 413

    from .auth import auth_bp
    from .repository_analysis_routes import repository_analysis_bp
    from .repository_api import repository_api_bp
    from .repository_pages import repository_pages_bp
    from .specification_artifacts import specification_artifacts_bp
    from .specification_generation import specification_generation_bp
    from .specification_projects import specification_projects_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(specification_generation_bp)
    app.register_blueprint(specification_projects_bp)
    app.register_blueprint(specification_artifacts_bp)
    app.register_blueprint(repository_pages_bp)
    app.register_blueprint(repository_analysis_bp)
    app.register_blueprint(repository_api_bp)
    return app
