"""Implant-document extraction endpoints.

Deliberately refused unless the backend is running locally. The cloud
deployment has no authentication and is documented as a public demo, so an
endpoint that accepts clinical documents must not exist there at all — not
merely be unadvertised. The guard is the same ``VOXTOOL_LOCAL`` flag the desktop
build already sets, so there is one switch rather than two.
"""
from __future__ import annotations

import os
import tempfile

from flask import Blueprint, jsonify, request

import local_mode
from extraction import pipeline, providers

extract_bp = Blueprint("extract", __name__)

ALLOWED_EXTENSIONS = (".pdf", ".pptx")
MAX_BYTES = 40 * 1024 * 1024


def _refuse_if_cloud():
    if not local_mode.is_local_mode():
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Document extraction is only available in the desktop app, "
                        "where the file and the model stay on your machine."
                    ),
                }
            ),
            403,
        )
    return None


@extract_bp.route("/status", methods=["GET"])
def status():
    """What the UI needs to decide which options to offer."""
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal
    return jsonify(
        {
            "success": True,
            "local": True,
            "providers": providers.available_providers(),
            "models": providers.ollama_models(),
            "default_model": providers.DEFAULT_MODEL,
        }
    )


@extract_bp.route("/leads", methods=["POST"])
def extract_leads():
    """Read an implant document and return proposed lead definitions."""
    refusal = _refuse_if_cloud()
    if refusal:
        return refusal

    provider = (request.form.get("provider") or "none").strip()
    model = (request.form.get("model") or "").strip() or None

    # Either an uploaded file or, for the desktop app, a path already on disk.
    path = (request.form.get("path") or "").strip()
    temp_path = None
    display_name = ""

    try:
        if path:
            if not os.path.isfile(path):
                return jsonify({"success": False, "error": f"No file at {path}"}), 404
            source = path
            display_name = os.path.basename(path)
        else:
            upload = request.files.get("file")
            if not upload or not upload.filename:
                return jsonify({"success": False, "error": "No document supplied."}), 400
            ext = os.path.splitext(upload.filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                return (
                    jsonify(
                        {
                            "success": False,
                            "error": f"Unsupported file type '{ext}'. Use PDF or PPTX.",
                        }
                    ),
                    400,
                )
            fd, temp_path = tempfile.mkstemp(suffix=ext)
            os.close(fd)
            upload.save(temp_path)
            display_name = os.path.basename(upload.filename)
            if os.path.getsize(temp_path) > MAX_BYTES:
                return jsonify({"success": False, "error": "Document is too large."}), 413
            source = temp_path

        result = pipeline.run(source, provider=provider, model=model)
        payload = result.to_json()
        payload["success"] = True
        # The caller's own filename, never the temp path we saved it under.
        payload["document"]["name"] = display_name
        return jsonify(payload)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:  # noqa: BLE001 - surface the reason, do not 500 blankly
        return jsonify({"success": False, "error": f"Extraction failed: {e}"}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
