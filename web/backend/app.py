import os
import sys

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

import local_mode
from routes.scans import scans_bp
from routes.annotations import annotations_bp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _cors_origins():
    raw = os.environ.get("CORS_ALLOWED_ORIGINS", "")
    if raw.strip():
        return [o.strip() for o in raw.split(",") if o.strip()]
    return ["http://localhost:3000"]


def _static_dir():
    """Locate the compiled React bundle that the desktop build serves itself."""
    override = os.environ.get("VOXTOOL_STATIC_DIR")
    if override and os.path.isdir(override):
        return override

    meipass = getattr(sys, "_MEIPASS", "")
    # Frozen onedir (PyInstaller 6+): exe sits next to _internal/; older layouts
    # keep datas beside the exe. Probe both so a packaging change cannot blank
    # the UI with a black Electron window.
    exe_dir = ""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))

    candidates = [
        os.path.join(meipass, "frontend") if meipass else "",
        os.path.join(BASE_DIR, "frontend"),
        os.path.join(exe_dir, "frontend") if exe_dir else "",
        os.path.join(exe_dir, "_internal", "frontend") if exe_dir else "",
        os.path.join(os.path.dirname(BASE_DIR), "frontend", "build"),
    ]
    for path in candidates:
        if path and os.path.isfile(os.path.join(path, "index.html")):
            return path
    return ""


def create_app():
    # Flask's built-in /static route would shadow serve_ui and 404 the CRA bundle.
    app = Flask(__name__, static_folder=None)
    CORS(app, origins=_cors_origins())

    app.config["DATA_DIR"] = os.path.join(BASE_DIR, "data")
    app.config["ANNOTATIONS_DIR"] = os.path.join(BASE_DIR, "annotations")
    app.config["BUNDLED_CLOUD_DIR"] = os.path.join(BASE_DIR, "cloud_caches")

    if local_mode.is_local_mode():
        # Desktop keeps writable state in the per-user app folder so the install
        # directory can stay read-only, and opens scans in place with no size cap.
        app.config["DATA_DIR"] = os.path.join(local_mode.app_data_dir(), "data")
        app.config["ANNOTATIONS_DIR"] = os.path.join(
            local_mode.app_data_dir(), "annotations"
        )
    else:
        app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024  # 150 MB NIfTI uploads

    os.makedirs(app.config["DATA_DIR"], exist_ok=True)
    os.makedirs(app.config["ANNOTATIONS_DIR"], exist_ok=True)

    app.register_blueprint(scans_bp, url_prefix="/api/scans")
    app.register_blueprint(annotations_bp, url_prefix="/api/annotations")

    static_dir = _static_dir()
    app.config["STATIC_DIR"] = static_dir

    @app.route("/api/health")
    def health():
        commit = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("GITHUB_SHA") or "local"
        return jsonify(
            {
                "status": "ok",
                "build": commit[:8],
                "local": local_mode.is_local_mode(),
                "data_dir": app.config["DATA_DIR"],
                "ui": bool(static_dir),
                "static_dir": static_dir or None,
            }
        )

    if static_dir:
        @app.route("/", defaults={"path": ""})
        @app.route("/<path:path>")
        def serve_ui(path):
            if path:
                full = os.path.normpath(os.path.join(static_dir, path))
                # Stay inside the UI folder even if a request tries ".." segments.
                if not full.startswith(os.path.normpath(static_dir) + os.sep) and full != os.path.normpath(static_dir):
                    return ("Not found", 404)
                if os.path.isfile(full):
                    return send_from_directory(static_dir, path)
                # Missing JS/CSS must 404 — falling back to index.html makes the
                # browser try to execute HTML as JavaScript and leaves a blank UI.
                if path.startswith("static/") or path.endswith((".js", ".css", ".map", ".woff", ".woff2", ".png", ".svg")):
                    return ("Not found", 404)
            return send_from_directory(static_dir, "index.html")
    else:
        @app.route("/")
        def root_health():
            return (
                "VoxTool backend is running, but the UI bundle was not found. "
                "Reinstall or rebuild the desktop app.",
                200,
                {"Content-Type": "text/plain; charset=utf-8"},
            )

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    # Desktop binds loopback only: nothing on the network can reach the scans.
    host = "127.0.0.1" if local_mode.is_local_mode() else "0.0.0.0"
    app.run(host=host, port=port, debug=debug, threaded=True)
