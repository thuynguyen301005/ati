from flask import Blueprint, jsonify, request, send_file

from services.specification_artifact_service import (
    build_project_archive,
    run_project_tests,
)
from services.specification_service import (
    get_project,
    update_project_artifact,
)
from .auth import current_user_id, login_required


specification_artifacts_bp = Blueprint("specification_artifacts", __name__)


@specification_artifacts_bp.route("/api/spec/<project_id>/artifacts/<key>", methods=["PUT"])
@login_required
def update_artifact(project_id, key):
    """Save an edited artifact and rerender its diagrams when needed."""
    project = get_project(current_user_id(), project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404
    if key not in project["artifacts"]:
        return jsonify({"error": f"Artifact '{key}' not found."}), 404

    artifact = request.get_json() or {}
    if not isinstance(artifact.get("content"), dict):
        return jsonify({"error": "Artifact content must be a JSON object."}), 400
    project = update_project_artifact(current_user_id(), project, key, artifact)
    return jsonify({"project": project})


@specification_artifacts_bp.route("/api/spec/<project_id>/export", methods=["GET"])
@login_required
def export_specification(project_id):
    project = get_project(current_user_id(), project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404

    return send_file(
        build_project_archive(project),
        mimetype="application/zip",
        as_attachment=True,
        download_name="specforge-project.zip",
    )


@specification_artifacts_bp.route("/api/spec/<project_id>/run-tests", methods=["POST"])
@login_required
def run_generated_tests(project_id):
    project = get_project(current_user_id(), project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404
    result, status_code = run_project_tests(project)
    return jsonify(result), status_code
