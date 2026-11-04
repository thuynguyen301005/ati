import uuid

from flask import Blueprint, jsonify, request

from services.git_repo import clone_git_repo_and_load_files
from services.repository_analysis import analyze_repository_files
from . import state


repository_analysis_bp = Blueprint("repository_analysis", __name__)


def _process_repository_files(
    files: dict[str, str],
    repo_name: str,
    repo_path: str,
    source: str,
    size_error_template: str,
    no_valid_files_error: str,
    all_files_failed_error: str,
):
    total_size_bytes = sum(len(content.encode("utf-8")) for content in files.values())
    total_kb = total_size_bytes / 1024
    if total_kb > 100:
        return jsonify({"error": size_error_template.format(total_kb=total_kb)}), 400

    allowed_ext = (".py", ".html", ".css", ".js")
    valid_files = {
        name: content
        for name, content in files.items()
        if name.lower().endswith(allowed_ext)
    }

    if not valid_files:
        return jsonify({"error": no_valid_files_error}), 400

    analysis, errors, graphviz_error = analyze_repository_files(valid_files)
    repo_id = str(uuid.uuid4())
    repository = {
        **analysis,
        "name": repo_name,
        "path": repo_path,
        "source": source,
    }

    if analysis["summary"]["processed"] == 0:
        repository["review_error"] = all_files_failed_error
        state.REPOS[repo_id] = repository
        return jsonify({
            "error": all_files_failed_error,
            "details": errors,
        }), 500

    state.REPOS[repo_id] = repository

    return jsonify({
        "repo_id": repo_id,
        "summary": repository["summary"],
        "has_review": bool(repository["review"]),
        "graphviz_error": graphviz_error,
        "repo_name": repo_name,
        "repo_path": repo_path,
        "source": source,
    })


@repository_analysis_bp.route("/generate", methods=["POST"])
def generate():
    """Validate local folder input and analyze its code files."""
    data = request.get_json() or {}
    files = data.get("files")
    repo_name = data.get("repo_name", "Local repo")
    repo_path = data.get("repo_path", "Local folder")

    if files is None:
        return jsonify({"error": "Không nhận được dữ liệu files từ client."}), 400

    if isinstance(files, dict) and len(files) == 0:
        return jsonify({"error": "Folder bạn chọn đang rỗng, không có file nào."}), 400

    return _process_repository_files(
        files,
        repo_name,
        repo_path,
        "local",
        "Folder quá lớn ({total_kb:.2f} KB). Vui lòng chọn folder nhỏ hơn 100KB.",
        "No valid code files (.py, .html, .css, .js) found",
        "All files failed to process.",
    )


@repository_analysis_bp.route("/add_git_repo", methods=["POST"])
def add_git_repo():
    """Clone a Git repository and analyze its source files."""
    data = request.get_json() or {}
    git_url = data.get("git_url", "").strip()

    if not git_url:
        return jsonify({"error": "git_url is required"}), 400

    files, clone_error = clone_git_repo_and_load_files(git_url)
    if clone_error:
        return jsonify({"error": clone_error}), 400

    repo_name = git_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]

    return _process_repository_files(
        files,
        repo_name,
        git_url,
        "git",
        "Git repo quá lớn ({total_kb:.2f} KB) theo giới hạn 100KB của demo.",
        "No valid code files (.py, .html, .css, .js) found in git repo",
        "All files failed to process from git repo.",
    )
