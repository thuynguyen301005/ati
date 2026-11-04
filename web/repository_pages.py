from flask import Blueprint, render_template

from . import state


repository_pages_bp = Blueprint("repository_pages", __name__)


@repository_pages_bp.route("/repo/<repo_id>")
def repo_view(repo_id):
    repo = state.REPOS.get(repo_id)
    if not repo:
        return render_template(
            "repo.html",
            repo_name="Repo not found",
            repo_path="",
            repo_id=repo_id,
        )

    return render_template(
        "repo.html",
        repo_name=repo.get("name", "Local repo"),
        repo_path=repo.get("path", "Local folder"),
        repo_id=repo_id,
    )
