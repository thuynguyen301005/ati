from flask import Blueprint, jsonify, request

from services.document_reader import extract_text
from services.spec_agent import STAGE_KEYS
from services.specification_service import create_project
from .auth import current_user_id, login_required


specification_generation_bp = Blueprint("specification_generation", __name__)
MAX_REQUIREMENT_CHARS = 30000


@specification_generation_bp.route("/api/spec/generate", methods=["POST"])
@login_required
def generate_specification():
    data = request.get_json() or {}
    requirement = (data.get("requirement") or "").strip()
    if len(requirement) < 20:
        return jsonify({"error": "Requirement must contain at least 20 characters."}), 400
    if len(requirement) > MAX_REQUIREMENT_CHARS:
        return jsonify({
            "error": f"Requirement is too large. Keep it under {MAX_REQUIREMENT_CHARS:,} characters."
        }), 400

    stages = data.get("stages")
    if stages is not None:
        if not isinstance(stages, list) or not stages:
            return jsonify({"error": "Select at least one pipeline stage."}), 400
        unknown = [stage for stage in stages if stage not in STAGE_KEYS]
        if unknown:
            return jsonify({"error": f"Unknown stages: {', '.join(map(str, unknown))}"}), 400

    project, error = create_project(current_user_id(), requirement, stages)
    if error or not project:
        return jsonify({"error": error or "Unable to generate the software plan."}), 502
    return jsonify({"project_id": project["id"], "project": project})


@specification_generation_bp.route("/api/spec/upload", methods=["POST"])
@login_required
def upload_specification():
    """Read an uploaded specification and return its text for the requirement field."""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded."}), 400

    text, error = extract_text(file.filename, file.read())
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"filename": file.filename, "text": text, "chars": len(text)})
