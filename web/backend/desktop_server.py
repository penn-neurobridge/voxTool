"""Entry point for the frozen desktop backend.

Runs the same Flask app the cloud deployment uses, but behind waitress (works on
Windows, unlike gunicorn) and bound to loopback so the API is unreachable from
the network. Electron passes the port in and waits for /api/health.
"""
from __future__ import annotations

import os
import sys

# PyInstaller runs this as __main__ from a temp dir; make sibling modules importable.
if getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("VOXTOOL_LOCAL", "1")
# The cloud deployment sets this (see terraform/backend.tf). Matching it keeps
# both environments on the same threshold-cloud code path — in-RAM volume rather
# than mmap'd z-slabs — so snap and interpolate agree with the web app.
os.environ.setdefault("ENABLE_VOLUME_WARM", "1")

from app import create_app  # noqa: E402


def main() -> int:
    port = int(os.environ.get("PORT", "5001"))
    application = create_app()

    try:
        from waitress import serve
    except ImportError:
        application.run(host="127.0.0.1", port=port, threaded=True, debug=False)
        return 0

    print(f"VoxTool backend listening on 127.0.0.1:{port}", flush=True)
    # Threads cover the UI's parallel polling (cloud_ready, volume_ready) while a
    # threshold cloud builds; the build itself runs on its own daemon thread.
    serve(
        application,
        host="127.0.0.1",
        port=port,
        threads=8,
        channel_timeout=1800,
        ident="VoxTool",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
