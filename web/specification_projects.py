from flask import Blueprint, jsonify, request

from services.specification_service import (
    MAX_CHAT_MESSAGE_CHARS,
    delete_project,
    get_project,
    list_projects,
    rename_project,
    revise_saved_project,
)
from .auth import current_user_id, login_required


specification_projects_bp = Blueprint("specification_projects", __name__)


@specification_projects_bp.route("/api/spec/projects", methods=["GET"])
@login_required
def list_specifications():
    return jsonify({"projects": list_projects(current_user_id())})


@specification_projects_bp.route("/api/spec/<project_id>", methods=["GET"])
@login_required
def get_specification(project_id):
    project = get_project(current_user_id(), project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404
    return jsonify({"project": project})


@specification_projects_bp.route("/api/spec/<project_id>", methods=["PATCH"])
@login_required
def rename_specification(project_id):
    project = get_project(current_user_id(), project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404
    title = ((request.get_json() or {}).get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title cannot be empty."}), 400
    project = rename_project(current_user_id(), project, title)
    return jsonify({"project": project})


@specification_projects_bp.route("/api/spec/<project_id>", methods=["DELETE"])
@login_required
def delete_specification(project_id):
    if not delete_project(current_user_id(), project_id):
        return jsonify({"error": "specification project not found"}), 404
    return jsonify({"deleted": project_id})


@specification_projects_bp.route("/api/spec/<project_id>/chat", methods=["POST"])
@login_required
def chat_specification(project_id):
    """Chat on a project and update the affected artifacts."""
    project = get_project(current_user_id(), project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404
    message = ((request.get_json() or {}).get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message cannot be empty."}), 400
    if len(message) > MAX_CHAT_MESSAGE_CHARS:
        return jsonify({
            "error": f"Message is too long (max {MAX_CHAT_MESSAGE_CHARS:,} characters)."
        }), 400

    updated_project, reply, updated, agent_error = revise_saved_project(
        current_user_id(), project, message
    )
    if agent_error or not updated_project:
        return jsonify({"error": agent_error or "The agent could not answer."}), 502
    return jsonify({"project": updated_project, "reply": reply, "updated": updated})
