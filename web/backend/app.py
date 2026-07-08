import os
from flask import Flask
from flask_cors import CORS
from routes.scans import scans_bp
from routes.annotations import annotations_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _cors_origins():
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    if raw.strip():
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:3000"]


def create_app():
    app = Flask(__name__)
    CORS(app, origins=_cors_origins())

    app.config["DATA_DIR"] = os.path.join(BASE_DIR, "data")
    app.config["ANNOTATIONS_DIR"] = os.path.join(BASE_DIR, "annotations")
    app.config["BUNDLED_CLOUD_DIR"] = os.path.join(BASE_DIR, "cloud_caches")
    app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024  # 150 MB NIfTI uploads

    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    os.makedirs(app.config["ANNOTATIONS_DIR"], exist_ok=True)

    app.register_blueprint(scans_bp, url_prefix="/api/scans")
    app.register_blueprint(annotations_bp, url_prefix="/api/annotations")

    @app.route("/")
    def root_health():
        return "OK", 200

    @app.route("/api/health")
    def health():
        commit = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GITHUB_SHA") or "local"
        return {
            "status": "ok",
            "build": commit[:8],
        }

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
