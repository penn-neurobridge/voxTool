"""Upload finished annotations to Pennsieve, and open scans from it.

Local-only, for the same reason as document extraction: the cloud deployment
has no authentication, and these endpoints would let anyone who found them
read or write the lab's Pennsieve workspace using this machine's credentials.

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
import pennsieve_api
import pennsieve_connect
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


def _unexpected(e: Exception):
    """Report an unforeseen failure by type only.

    These handlers read Pennsieve's config and talk to the agent, so an
    exception's message can carry a credential: one already quoted an API
    secret from config.ini. Letting it propagate would print it in the server
    log, and echoing it would show it in the UI.
    """
    return jsonify({
        "success": False,
        "error": f"Unexpected {type(e).__name__} while talking to Pennsieve.",
    }), 500


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
    payload["profiles"] = pennsieve_connect.profiles()
    payload["profile"] = ""
    if st.agent_running:
        # The REST list says which datasets this account may add files to;
        # the CLI's does not. Keep the CLI's if the API cannot be reached.
        try:
            payload["datasets"] = pennsieve_api.datasets(
                limited=request.args.get("all") != "1"
            )
            payload["profile"] = pennsieve_api.session().profile
        except Exception:  # noqa: BLE001
            pass
    payload["success"] = True
    return jsonify(payload)


@pennsieve_bp.route("/connect", methods=["POST"])
def connect():
    """Save an API key as a profile and switch to it. Body: {api_key, api_secret, force}.

    The key and secret never appear in a response, an error, or a log: only
    PennsieveError messages (written without them) and exception type names
    come back.
    """
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    api_key = body.get("api_key")
    api_secret = body.get("api_secret")
    if not (isinstance(api_key, str) and isinstance(api_secret, str)):
        return jsonify({"success": False, "error": "Paste both the API key and the secret."}), 400
    try:
        result = pennsieve_connect.connect(api_key, api_secret, force=body.get("force") is True)
    except pennsieve_connect.PennsieveBusy as e:
        return jsonify({"success": False, "busy": True, "error": str(e)}), 409
    except pennsieve_sync.PennsieveError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return _unexpected(e)
    result["success"] = True
    return jsonify(result)


@pennsieve_bp.route("/switch", methods=["POST"])
def switch_profile():
    """Switch to a saved profile. Body: {profile, force}."""
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    profile = (body.get("profile") or "").strip()
    try:
        result = pennsieve_connect.switch(profile, force=body.get("force") is True)
    except pennsieve_connect.PennsieveBusy as e:
        return jsonify({"success": False, "busy": True, "error": str(e)}), 409
    except pennsieve_sync.PennsieveError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:  # noqa: BLE001
        return _unexpected(e)
    result["success"] = True
    return jsonify(result)


@pennsieve_bp.route("/settings", methods=["GET", "POST"])
def settings():
    """This computer's dataset limit. Body: {allowed_datasets: [N:dataset:…]}, [] for none."""
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal
    if request.method == "POST":
        ids = (request.get_json(silent=True) or {}).get("allowed_datasets")
        if not isinstance(ids, list) or not all(
            isinstance(i, str) and i.startswith("N:dataset:") for i in ids
        ):
            return jsonify({"success": False, "error": "Expected a list of dataset IDs."}), 400
        current = pennsieve_sync.load_settings()
        current["allowed_datasets"] = sorted(set(ids))
        pennsieve_sync.save_settings(current)
    return jsonify({
        "success": True,
        "allowed_datasets": sorted(pennsieve_sync.allowed_datasets()),
        # An environment variable overrides the saved setting, e.g. in tests.
        "overridden": bool(os.environ.get("VOXTOOL_PENNSIEVE_DATASETS", "").strip()),
    })


@pennsieve_bp.route("/browse", methods=["GET"])
def browse():
    """One folder of a dataset. Query: dataset=<N:dataset:…>, folder=<N:collection:…>."""
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal
    dataset_id = (request.args.get("dataset") or "").strip()
    folder_id = (request.args.get("folder") or "").strip()
    if not dataset_id:
        return jsonify({"success": False, "error": "Choose a dataset first."}), 400
    try:
        listing = pennsieve_api.browse(dataset_id, folder_id)
    except pennsieve_sync.PennsieveError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return _unexpected(e)
    listing["success"] = True
    return jsonify(listing)


@pennsieve_bp.route("/open", methods=["POST"])
def open_scan():
    """Download a scan by its Pennsieve ID. Body: {package_id: <N:package:…>}.

    Returns the local path; the UI opens it through /api/scans/open_local, the
    same as a scan picked from disk.
    """
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal
    body = request.get_json(silent=True) or {}
    package_id = (body.get("package_id") or "").strip()
    if not package_id.startswith("N:package:"):
        return jsonify({
            "success": False,
            "error": "Paste a Pennsieve file ID; it starts with N:package:",
        }), 400
    try:
        result = pennsieve_api.download_scan(package_id)
    except pennsieve_sync.PennsieveError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return _unexpected(e)
    result["success"] = True
    return jsonify(result)


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

    # Checked before anything is written, preview included: a viewer's upload
    # would only fail later, inside the agent, after the transfer.
    try:
        role = pennsieve_api.dataset_role(dataset_id)
    except pennsieve_sync.PennsieveError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return _unexpected(e)
    if role not in pennsieve_api.EDIT_ROLES:
        return jsonify({
            "success": False,
            "error": f"This account is a {role or 'non-member'} of that dataset; uploading "
                     "needs editor access or above. Ask the dataset's owner.",
        }), 403

    # A folder given by ID is resolved here, against the chosen dataset, rather
    # than trusting a path the client worked out.
    folder_id = (body.get("target_folder_id") or "").strip()
    if folder_id:
        try:
            target_path = pennsieve_api.folder_path(dataset_id, folder_id)
        except pennsieve_sync.PennsieveError as e:
            return jsonify({"success": False, "error": str(e)}), 502
        except Exception as e:  # noqa: BLE001
            return _unexpected(e)

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
