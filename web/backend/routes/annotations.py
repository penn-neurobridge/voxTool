import json
import os
import uuid
from flask import Blueprint, request, jsonify, current_app

annotations_bp = Blueprint("annotations", __name__)


def _annotations_dir():
    d = current_app.config["ANNOTATIONS_DIR"]
    os.makedirs(d, exist_ok=True)
    return d


@annotations_bp.route("/", methods=["POST"])
def save_annotation():
    body = request.get_json(force=True)
    scan_id = body.get("scan_id")
    if not scan_id:
        return jsonify({"error": "scan_id is required"}), 400

    annotation_id = body.get("id") or str(uuid.uuid4())
    body["id"] = annotation_id

    filepath = os.path.join(_annotations_dir(), f"{scan_id}.json")

    existing = []
    if os.path.isfile(filepath):
        with open(filepath) as f:
            existing = json.load(f)

    # Replace if same id exists, else append
    replaced = False
    for i, ann in enumerate(existing):
        if ann.get("id") == annotation_id:
            existing[i] = body
            replaced = True
            break
    if not replaced:
        existing.append(body)

    with open(filepath, "w") as f:
        json.dump(existing, f, indent=2)

    return jsonify({"id": annotation_id, "status": "saved"}), 201


@annotations_bp.route("/<scan_id>", methods=["GET"])
def get_annotations(scan_id):
    filepath = os.path.join(_annotations_dir(), f"{scan_id}.json")
    if not os.path.isfile(filepath):
        return jsonify([])
    with open(filepath) as f:
        data = json.load(f)
    return jsonify(data)
