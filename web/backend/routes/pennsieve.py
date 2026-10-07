"""Upload finished annotations to Pennsieve.

Local-only, for the same reason as document extraction: the cloud deployment
has no authentication, and this endpoint would let anyone who found it push
files into the lab's Pennsieve workspace using this machine's credentials.

Sending defaults to off. A caller has to ask for a real upload explicitly, so
a bug or a mis-wired button reports a plan instead of putting a patient file
somewhere nobody intended.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time

from flask import Blueprint, jsonify, request

import local_mode
import pennsieve_sync

pennsieve_bp = Blueprint("pennsieve", __name__)


def _refuse_if_cloud():
    if not local_mode.is_local_mode():
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Pennsieve upload is only available in the desktop app, "
                        "which uses the Pennsieve account signed in on this machine."
                    ),
                }
            ),
            403,
        )
    return None


@pennsieve_bp.route("/status", methods=["GET"])
def status():
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal
    auto = request.args.get("auto_start", "").lower() in ("1", "true", "yes")
    try:
        st = pennsieve_sync.status(auto_start=auto)
    except pennsieve_sync.PennsieveError as e:
        return jsonify({"success": False, "error": str(e)}), 200
    payload = st.to_json()
    payload["success"] = True
    return jsonify(payload)


@pennsieve_bp.route("/upload", methods=["POST"])
def upload():
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal

    body = request.get_json(silent=True) or {}
    document = body.get("document")
    dataset_id = (body.get("dataset_id") or "").strip()
    target_path = (body.get("target_path") or "").strip()
    scan_filename = (body.get("scan_filename") or "").strip()
    # Opt in, never default on.
    dry_run = body.get("dry_run", True) is not False
    # "json" is VoxTool's full document; "txt" is the legacy tab-separated
    # layout of the lab's electrodes.txt, built by the frontend's exporter.
    formats = body.get("formats") or ["json"]
    txt = body.get("txt")

    if not isinstance(document, dict) or not document.get("leads"):
        return jsonify({"success": False, "error": "Nothing to upload — no annotations."}), 400
    if not dataset_id:
        return jsonify({"success": False, "error": "Choose a dataset first."}), 400
    if not isinstance(formats, list) or not set(formats) <= {"json", "txt"}:
        return jsonify({"success": False, "error": "Formats must be json and/or txt."}), 400
    if "txt" in formats and not (isinstance(txt, str) and txt.strip()):
        return jsonify({"success": False, "error": "No TXT to upload — no marked contacts."}), 400

    when = time.time()
    contents = {}
    if "json" in formats:
        contents[pennsieve_sync.remote_filename(scan_filename, when)] = json.dumps(document, indent=2)
    if "txt" in formats:
        contents[pennsieve_sync.remote_filename(scan_filename, when, ext="txt")] = txt

    staging_dir = tempfile.mkdtemp(dir=pennsieve_sync.outbox_dir())
    keep = False
    try:
        paths = []
        for name, text in contents.items():
            # Written under its final name: the agent uses the filename on disk
            # as the name in the dataset.
            path = os.path.join(staging_dir, name)
            with open(path, "w") as f:
                f.write(text)
            paths.append(path)

        result = pennsieve_sync.upload(
            paths,
            dataset_id=dataset_id,
            target_path=target_path,
            dry_run=dry_run,
        )
        # The agent is still reading them; deleting now would drop the upload.
        keep = result.get("state") == "pending"
        result["success"] = True
        result["filename"] = result["file"]
        return jsonify(result)
    except pennsieve_sync.PennsieveError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"success": False, "error": f"Upload failed: {e}"}), 500
    finally:
        if not keep:
            shutil.rmtree(staging_dir, ignore_errors=True)
