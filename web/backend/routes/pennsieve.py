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
import tempfile

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

    if not isinstance(document, dict) or not document.get("leads"):
        return jsonify({"success": False, "error": "Nothing to upload — no annotations."}), 400
    if not dataset_id:
        return jsonify({"success": False, "error": "Choose a dataset first."}), 400

    name = pennsieve_sync.remote_filename(scan_filename)
    tmp_dir = tempfile.mkdtemp(prefix="voxtool-pennsieve-")
    # Written under its final name: the agent uses the filename on disk as the
    # name in the dataset.
    local_path = os.path.join(tmp_dir, name)
    try:
        with open(local_path, "w") as f:
            json.dump(document, f, indent=2)

        result = pennsieve_sync.upload(
            local_path,
            dataset_id=dataset_id,
            target_path=target_path,
            dry_run=dry_run,
        )
        result["success"] = True
        result["filename"] = name
        return jsonify(result)
    except pennsieve_sync.PennsieveError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"success": False, "error": f"Upload failed: {e}"}), 500
    finally:
        try:
            os.remove(local_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass
