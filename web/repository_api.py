from flask import Blueprint, jsonify, request

from services.repository_chat import chat_about_repo_with_gemini
from . import state


repository_api_bp = Blueprint("repository_api", __name__)


@repository_api_bp.route("/api/repo/<repo_id>/chat", methods=["POST"])
def api_repo_chat(repo_id):
    """Answer a question about an analyzed repository."""
    repo = state.REPOS.get(repo_id)
    if not repo:
        return jsonify({"error": "repo not found"}), 404

    data = request.get_json() or {}
    question = (data.get("question") or "").strip()
    history = data.get("history") or []

    if not question:
        return jsonify({"error": "Missing question"}), 400

    answer, error = chat_about_repo_with_gemini(repo, question, history)
    if error or not answer:
        return jsonify({"error": "AI chat failed", "detail": error}), 500

    return jsonify({"answer": answer})


@repository_api_bp.route("/api/repo/<repo_id>/structure", methods=["GET"])
def api_structure(repo_id):
    repo = state.REPOS.get(repo_id)
    if not repo:
        return jsonify({"error": "repo not found"}), 404

    files = repo.get("files", {})
    items = []
    for path, info in files.items():
        items.append({
            "path": path,
            "status": info.get("status", "error"),
            "has_error": "error" in info,
        })
    return jsonify({
        "files": items,
        "summary": repo.get("summary", {}),
    })


@repository_api_bp.route("/api/repo/<repo_id>/file/<path:file_path>", methods=["GET"])
def api_file(repo_id, file_path):
    repo = state.REPOS.get(repo_id)
    if not repo:
        return jsonify({"error": "repo not found"}), 404

    info = repo.get("files", {}).get(file_path)
    if not info:
        return jsonify({"error": "file not found"}), 404
    return jsonify(info)


@repository_api_bp.route("/api/repo/<repo_id>/graph", methods=["GET"])
def api_graph(repo_id):
    repo = state.REPOS.get(repo_id)
    if not repo:
        return jsonify({"error": "repo not found"}), 404

    svg_data = repo.get("diagram_svg")
    if not svg_data:
        return jsonify({
            "error": "no diagram",
            "graphviz_error": repo.get("review_error"),
        }), 404
    return jsonify({"diagram": svg_data})


@repository_api_bp.route("/api/repo/<repo_id>/review", methods=["GET"])
def api_repo_review(repo_id):
    repo = state.REPOS.get(repo_id)
    if not repo:
        return jsonify({"error": "repo not found"}), 404

    review = repo.get("review")
    review_error = repo.get("review_error")

    if review is None and not review_error:
        return jsonify({
            "summary": "No review available.",
            "issues": [],
        })

    if review_error and not review:
        return jsonify({
            "summary": "Review failed.",
            "issues": [],
            "error": review_error,
        })

    return jsonify(review)


@repository_api_bp.route("/api/repo/<repo_id>", methods=["DELETE"])
def api_delete_repo(repo_id):
    if repo_id in state.REPOS:
        del state.REPOS[repo_id]
        return jsonify({"status": "deleted"})
    return jsonify({"error": "repo not found"}), 404
