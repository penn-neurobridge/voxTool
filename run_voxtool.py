#!/usr/bin/env python3
"""Run VoxTool locally from a source checkout.

This is the "clone it and run it in a terminal" route, the way the legacy PyQt
tool worked. It is not a second version of VoxTool: it starts the *same* Flask
backend and the *same* React UI that the desktop installer ships, just using the
Python and Node already on your machine instead of a frozen bundle. Scans are
read in place, nothing is uploaded, and the server listens on loopback only.

    python3 run_voxtool.py

First run creates a virtualenv, installs the backend dependencies, and compiles
the UI, so it takes a few minutes. After that it starts in a couple of seconds.

Only the standard library is used here, since this runs before anything is
installed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from typing import NoReturn

REPO = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(REPO, "web", "backend")
FRONTEND_DIR = os.path.join(REPO, "web", "frontend")
UI_BUILD = os.path.join(FRONTEND_DIR, "build")
REQUIREMENTS = os.path.join(BACKEND_DIR, "requirements-desktop.txt")
#: Written only by this launcher, so a bundle compiled for the cloud is never reused.
LOCAL_MARKER = os.path.join(UI_BUILD, ".voxtool-local-build")
VENV_DIR = os.path.join(REPO, ".venv")
STAMP = os.path.join(VENV_DIR, ".voxtool-requirements")

MIN_PYTHON = (3, 9)
IS_WINDOWS = os.name == "nt"


def fail(message: str, *hints: str) -> NoReturn:
    print(f"\nVoxTool: {message}", file=sys.stderr)
    for hint in hints:
        print(f"  {hint}", file=sys.stderr)
    raise SystemExit(1)


def step(message: str) -> None:
    print(f"==> {message}", flush=True)


# ── environment ────────────────────────────────────────────────────────────────


def venv_python(venv: str) -> str:
    if IS_WINDOWS:
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python")


def requirements_digest() -> str:
    with open(REQUIREMENTS, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def ensure_venv() -> str:
    """Create .venv and install backend dependencies, skipping work when current."""
    python = venv_python(VENV_DIR)
    digest = requirements_digest()

    if os.path.isfile(python) and os.path.isfile(STAMP):
        with open(STAMP, encoding="utf-8") as handle:
            if handle.read().strip() == digest:
                return python

    if not os.path.isfile(python):
        step("Creating a virtualenv in .venv (first run only)")
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", VENV_DIR],
                check=True,
            )
        except subprocess.CalledProcessError:
            fail(
                "could not create a virtualenv.",
                "On Debian/Ubuntu install it with: sudo apt install python3-venv",
                "Or manage your own environment and use: python3 run_voxtool.py --no-venv",
            )

    step("Installing backend dependencies (first run only)")
    result = subprocess.run(
        [python, "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
    )
    if result.returncode != 0:
        print("    (could not upgrade pip; continuing)", flush=True)

    try:
        subprocess.run([python, "-m", "pip", "install", "-r", REQUIREMENTS], check=True)
    except subprocess.CalledProcessError:
        fail(
            "installing the backend dependencies failed.",
            f"Try manually: {python} -m pip install -r {REQUIREMENTS}",
        )

    with open(STAMP, "w", encoding="utf-8") as handle:
        handle.write(digest)
    return python


def check_backend_imports(python: str) -> None:
    probe = "import flask, flask_cors, nibabel, numpy"
    result = subprocess.run([python, "-c", probe], capture_output=True, text=True)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()
        fail(
            "the backend dependencies are not importable.",
            detail[-1] if detail else "",
            f"Install them with: {python} -m pip install -r {REQUIREMENTS}",
        )

    # Optional: the server falls back to Flask's development server without it.
    missing = subprocess.run(
        [python, "-c", "import waitress"], capture_output=True, text=True
    ).returncode
    if missing:
        print("    (waitress not installed; using Flask's slower dev server)", flush=True)


def npm_command() -> list[str]:
    npm = shutil.which("npm")
    if not npm:
        fail(
            "Node.js is required to compile the user interface, and npm was not found.",
            "Install Node 18 or newer from https://nodejs.org and run this again.",
            "Already have a compiled UI? Put it in web/frontend/build and it will be used.",
        )
    # .cmd shims on Windows are not directly executable by CreateProcess.
    return ["cmd", "/c", "npm"] if IS_WINDOWS else [npm]


def ensure_frontend(rebuild: bool) -> None:
    index = os.path.join(UI_BUILD, "index.html")
    have_build = os.path.isfile(index)

    if have_build and os.path.isfile(LOCAL_MARKER) and not rebuild:
        return

    if have_build and not rebuild:
        # The API URL is compiled into the bundle. A build made for the cloud would
        # send this "local" UI straight back to AWS, so never reuse an unmarked one.
        step("Recompiling the UI (the existing build was not made for local use)")

    npm = npm_command()
    if not os.path.isdir(os.path.join(FRONTEND_DIR, "node_modules")):
        step("Installing UI packages (first run only, a few minutes)")
        try:
            subprocess.run(npm + ["ci"], cwd=FRONTEND_DIR, check=True)
        except subprocess.CalledProcessError:
            fail("npm ci failed.", f"Try it by hand in {FRONTEND_DIR}")

    step("Compiling the user interface (first run only)")
    env = dict(os.environ)
    # Empty API URL keeps the UI on relative paths, so it talks to whichever port
    # this launcher happens to pick. CI=false stops warnings failing the build.
    env["REACT_APP_API_URL"] = ""
    env["CI"] = "false"
    try:
        subprocess.run(npm + ["run", "build"], cwd=FRONTEND_DIR, check=True, env=env)
    except subprocess.CalledProcessError:
        fail("building the UI failed.", f"Try it by hand: cd {FRONTEND_DIR} && npm run build")

    if not os.path.isfile(index):
        fail("the UI build finished but produced no index.html.")

    with open(LOCAL_MARKER, "w", encoding="utf-8") as handle:
        handle.write("Built by run_voxtool.py with an empty REACT_APP_API_URL.\n")


# ── server ─────────────────────────────────────────────────────────────────────


def free_port(preferred: int | None) -> int:
    if preferred:
        return preferred
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(port: int, process: subprocess.Popen, timeout: float = 90.0):
    """Poll /api/health until the backend answers, or it dies, or we give up."""
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return None
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return response.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run VoxTool locally from this checkout.",
    )
    parser.add_argument("--port", type=int, default=None, help="fixed port (default: free port)")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument("--rebuild-ui", action="store_true", help="recompile the UI")
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="use the current Python instead of .venv (you install the requirements)",
    )
    args = parser.parse_args()

    if sys.version_info < MIN_PYTHON:
        fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is required "
            f"(this is {sys.version.split()[0]})."
        )
    if not os.path.isfile(REQUIREMENTS):
        fail(f"cannot find {REQUIREMENTS}.", "Run this script from inside the voxTool checkout.")

    python = sys.executable if args.no_venv else ensure_venv()
    check_backend_imports(python)
    ensure_frontend(args.rebuild_ui)

    port = free_port(args.port)
    env = dict(os.environ)
    env["VOXTOOL_LOCAL"] = "1"
    env["PORT"] = str(port)
    env["PYTHONUNBUFFERED"] = "1"
    # Absolute path so the backend serves this checkout's UI, whatever the cwd.
    env["VOXTOOL_STATIC_DIR"] = UI_BUILD

    step(f"Starting VoxTool on http://127.0.0.1:{port}")
    process = subprocess.Popen(
        [python, os.path.join(BACKEND_DIR, "desktop_server.py")],
        cwd=BACKEND_DIR,
        env=env,
    )

    health = wait_for_health(port, process)
    if health is None:
        process.poll()
        if process.returncode is None:
            process.terminate()
        fail(
            "the backend did not come up.",
            "Any error from it is printed above.",
        )

    url = f"http://127.0.0.1:{port}/"
    print()
    print(f"  VoxTool is running at {url}")
    print("  Scans are read from your disk in place. Nothing is uploaded.")
    print("  Press Ctrl+C to stop.")
    print()

    if not args.no_browser:
        webbrowser.open(url)

    try:
        process.wait()
    except KeyboardInterrupt:
        print("\nStopping VoxTool…")
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
