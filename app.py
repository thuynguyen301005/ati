from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for
from functools import wraps
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List
import requests

from services.analysis import (
    send_to_gemini,
    merge_dot_graphs,
    render_svg_from_dot,
    review_repo_with_gemini,
    GEMINI_API_URL,  # dùng lại URL đã khai báo trong services.analysis
)
from services.gemini_client import post_gemini
from services.git_repo import clone_git_repo_and_load_files
from services.spec_agent import STAGES, STAGE_KEYS, generate_software_plan, revise_project, validate_artifacts
from services.document_reader import extract_text
from services import db
from werkzeug.security import check_password_hash, generate_password_hash
from config import SECRET_KEY

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
db.init_db()
# Giới hạn file upload đặc tả.
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
MAX_REQUIREMENT_CHARS = 30000

# Lưu nhiều repo: repo_id -> analysis result
REPOS: Dict[str, Dict] = {}


# ========= ĐĂNG NHẬP =========

def current_user_id() -> int | None:
    return session.get("user_id")


def login_required(view):
    """Trang thì chuyển về /login, API thì trả 401."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user_id():
            if request.path.startswith("/api/"):
                return jsonify({"error": "Please sign in again."}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapper


def _safe_next(target: str | None) -> str:
    # Chỉ cho redirect nội bộ, tránh open redirect.
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("home")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user_id():
        return redirect(url_for("home"))
    error = None
    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = db.get_user_by_email(email)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session.permanent = True
            return redirect(_safe_next(request.args.get("next")))
        error = "Incorrect email or password."
    return render_template("auth.html", mode="login", error=error, email=email)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user_id():
        return redirect(url_for("home"))
    error = None
    email = ""
    name = ""
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not name or len(name) > 80:
            error = "Enter your name (up to 80 characters)."
        elif "@" not in email or len(email) > 254:
            error = "Enter a valid email address."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            user_id = db.create_user(email, generate_password_hash(password), name)
            if user_id is None:
                error = "An account with this email already exists."
            else:
                session.clear()
                session["user_id"] = user_id
                session.permanent = True
                return redirect(url_for("home"))
    return render_template("auth.html", mode="register", error=error, email=email, name=name)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ========= ROUTES CƠ BẢN =========

def _spec_page(project_id: str = ""):
    user = db.get_user(current_user_id())
    if not user:
        session.clear()
        return redirect(url_for("login"))
    if project_id and not db.get_project(user["id"], project_id):
        return redirect(url_for("home"))
    user["display_name"] = user.get("name") or user["email"].split("@")[0]
    return render_template("spec.html", user=user, project_id=project_id)


@app.route("/")
@login_required
def home():
    return _spec_page()


@app.route("/spec/<project_id>")
@login_required
def open_specification(project_id):
    return _spec_page(project_id)


def _render_project_diagrams(project: Dict[str, Any]) -> None:
    """Render lại SVG cho architecture + use case + activity từ DOT hiện có."""
    architecture = project["artifacts"].get("architecture", {}).get("content", {}) or {}
    dot_code = architecture.get("dot_code") if isinstance(architecture, dict) else None
    project["architecture_svg"], project["architecture_error"] = (
        render_svg_from_dot(dot_code) if dot_code else (None, None)
    )

    # Use case + activity diagram: render san SVG de frontend chi viec nhung vao.
    diagrams = project["artifacts"].get("diagrams", {}).get("content", {}) or {}
    project["diagram_svgs"] = {}
    project["diagram_errors"] = {}
    if not isinstance(diagrams, dict):
        return
    for name in ("use_case", "activity"):
        block = diagrams.get(name) or {}
        dot = block.get("dot_code") if isinstance(block, dict) else None
        if not dot:
            continue
        svg, error = render_svg_from_dot(dot)
        if svg:
            project["diagram_svgs"][name] = svg
        if error:
            project["diagram_errors"][name] = error


def _project_title(project: Dict[str, Any]) -> str:
    first = next(iter(project["artifacts"].values()), {})
    title = (first.get("title") if isinstance(first, dict) else None) or project["requirement"][:60]
    return str(title).strip()[:120] or "Untitled project"


STAGE_NAMES = {key: name for key, name, _ in STAGES}
MAX_CHAT_MESSAGE_CHARS = 4000


def _chat_message(role: str, content: str, updated: List[str] | None = None) -> Dict[str, Any]:
    message = {"role": role, "content": content, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if updated:
        message["updated"] = updated
    return message


def _load_project_or_404(project_id: str):
    project = db.get_project(current_user_id(), project_id)
    if not project:
        return None, (jsonify({"error": "specification project not found"}), 404)
    return project, None


@app.route("/api/spec/generate", methods=["POST"])
@login_required
def generate_specification():
    data = request.get_json() or {}
    requirement = (data.get("requirement") or "").strip()
    if len(requirement) < 20:
        return jsonify({"error": "Requirement must contain at least 20 characters."}), 400
    if len(requirement) > MAX_REQUIREMENT_CHARS:
        return jsonify({"error": f"Requirement is too large. Keep it under {MAX_REQUIREMENT_CHARS:,} characters."}), 400

    stages = data.get("stages")
    if stages is not None:
        if not isinstance(stages, list) or not stages:
            return jsonify({"error": "Select at least one pipeline stage."}), 400
        unknown = [stage for stage in stages if stage not in STAGE_KEYS]
        if unknown:
            return jsonify({"error": f"Unknown stages: {', '.join(map(str, unknown))}"}), 400

    project, error = generate_software_plan(requirement, stages)
    if error or not project:
        return jsonify({"error": error or "Unable to generate the software plan."}), 502

    project_id = str(uuid.uuid4())
    project["id"] = project_id
    project["title"] = _project_title(project)
    _render_project_diagrams(project)
    generated = list(project["artifacts"])
    project["messages"] = [
        _chat_message("user", requirement),
        _chat_message(
            "assistant",
            "Generated " + ", ".join(STAGE_NAMES[key] for key in generated)
            + ". Tell me what to change and I will update the documents.",
            generated,
        ),
    ]
    db.save_project(current_user_id(), project)
    return jsonify({"project_id": project_id, "project": project})


@app.route("/api/spec/upload", methods=["POST"])
@login_required
def upload_specification():
    """Đọc file đặc tả và trả về text để điền vào ô requirement."""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "No file uploaded."}), 400

    text, error = extract_text(file.filename, file.read())
    if error:
        return jsonify({"error": error}), 400
    return jsonify({"filename": file.filename, "text": text, "chars": len(text)})


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({"error": "File is too large (max 10 MB)."}), 413


@app.route("/api/spec/projects", methods=["GET"])
@login_required
def list_specifications():
    return jsonify({"projects": db.list_projects(current_user_id())})


@app.route("/api/spec/<project_id>", methods=["GET"])
@login_required
def get_specification(project_id):
    project, error = _load_project_or_404(project_id)
    if error:
        return error
    return jsonify({"project": project})


@app.route("/api/spec/<project_id>", methods=["PATCH"])
@login_required
def rename_specification(project_id):
    project, error = _load_project_or_404(project_id)
    if error:
        return error
    title = ((request.get_json() or {}).get("title") or "").strip()
    if not title:
        return jsonify({"error": "Title cannot be empty."}), 400
    project["title"] = title[:120]
    db.save_project(current_user_id(), project)
    return jsonify({"project": project})


@app.route("/api/spec/<project_id>", methods=["DELETE"])
@login_required
def delete_specification(project_id):
    if not db.delete_project(current_user_id(), project_id):
        return jsonify({"error": "specification project not found"}), 404
    return jsonify({"deleted": project_id})


@app.route("/api/spec/<project_id>/chat", methods=["POST"])
@login_required
def chat_specification(project_id):
    """Chat tiếp trên project: AI trả lời và sửa các artifact liên quan."""
    project, error = _load_project_or_404(project_id)
    if error:
        return error
    message = ((request.get_json() or {}).get("message") or "").strip()
    if not message:
        return jsonify({"error": "Message cannot be empty."}), 400
    if len(message) > MAX_CHAT_MESSAGE_CHARS:
        return jsonify({"error": f"Message is too long (max {MAX_CHAT_MESSAGE_CHARS:,} characters)."}), 400

    result, agent_error = revise_project(project, message)
    if agent_error or not result:
        return jsonify({"error": agent_error or "The agent could not answer."}), 502

    updates = result["updates"]
    for key, artifact in updates.items():
        project["artifacts"][key] = {
            "title": str(artifact.get("title") or STAGE_NAMES[key]),
            "summary": str(artifact.get("summary") or ""),
            "content": artifact["content"],
        }
    # Giữ thứ tự pipeline cho tab và danh sách stage.
    project["artifacts"] = {key: project["artifacts"][key] for key in STAGE_KEYS if key in project["artifacts"]}
    project["stages"] = list(project["artifacts"])
    if "architecture" in updates or "diagrams" in updates:
        _render_project_diagrams(project)
    project["validation"] = validate_artifacts(project["artifacts"], project["stages"])

    messages = project.setdefault("messages", [])
    messages.append(_chat_message("user", message))
    messages.append(_chat_message("assistant", result["reply"], list(updates)))
    db.save_project(current_user_id(), project)
    return jsonify({"project": project, "reply": result["reply"], "updated": list(updates)})


@app.route("/api/spec/<project_id>/artifacts/<key>", methods=["PUT"])
@login_required
def update_artifact(project_id, key):
    """Lưu bản sửa của một artifact, rồi render lại sơ đồ nếu DOT thay đổi."""
    project, error = _load_project_or_404(project_id)
    if error:
        return error
    if key not in project["artifacts"]:
        return jsonify({"error": f"Artifact '{key}' not found."}), 404

    artifact = request.get_json() or {}
    if not isinstance(artifact.get("content"), dict):
        return jsonify({"error": "Artifact content must be a JSON object."}), 400
    project["artifacts"][key] = {
        "title": str(artifact.get("title") or "").strip() or key,
        "summary": str(artifact.get("summary") or ""),
        "content": artifact["content"],
    }
    if key in ("architecture", "diagrams"):
        _render_project_diagrams(project)
    stages = project.get("stages") or list(project["artifacts"])
    project["validation"] = validate_artifacts(project["artifacts"], stages)
    db.save_project(current_user_id(), project)
    return jsonify({"project": project})


def _safe_generated_path(path: str) -> Path | None:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    candidate = Path(normalized)
    if not normalized or ".." in candidate.parts:
        return None
    return candidate


@app.route("/api/spec/<project_id>/export", methods=["GET"])
@login_required
def export_specification(project_id):
    project, error = _load_project_or_404(project_id)
    if error:
        return error

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("SPECIFICATION.md", project.get("requirement", ""))
        bundle.writestr("validation.json", json.dumps(project.get("validation", {}), indent=2))
        if project.get("architecture_svg"):
            bundle.writestr("docs/architecture.svg", project["architecture_svg"])
        for name, svg in (project.get("diagram_svgs") or {}).items():
            bundle.writestr(f"docs/{name.replace('_', '-')}-diagram.svg", svg)
        for stage in ("code", "tests", "docs"):
            files = project["artifacts"].get(stage, {}).get("content", {}).get("files", [])
            for file in files:
                safe_path = _safe_generated_path(file.get("path", ""))
                if safe_path:
                    bundle.writestr(str(Path(stage) / safe_path), file.get("code", ""))
        for key, artifact in project.get("artifacts", {}).items():
            bundle.writestr(f"artifacts/{key}.json", json.dumps(artifact, indent=2))
    archive.seek(0)
    return send_file(archive, mimetype="application/zip", as_attachment=True, download_name="specforge-project.zip")


@app.route("/api/spec/<project_id>/run-tests", methods=["POST"])
@login_required
def run_generated_tests(project_id):
    project, error = _load_project_or_404(project_id)
    if error:
        return error

    code_files = project["artifacts"].get("code", {}).get("content", {}).get("files", [])
    test_files = project["artifacts"].get("tests", {}).get("content", {}).get("files", [])
    python_files = [file for file in code_files + test_files if file.get("path", "").endswith(".py")]
    if not python_files:
        return jsonify({"status": "skipped", "message": "No Python tests were generated."})

    with tempfile.TemporaryDirectory(prefix="specforge-") as temp_dir:
        root = Path(temp_dir)
        for file in python_files:
            safe_path = _safe_generated_path(file.get("path", ""))
            if not safe_path:
                continue
            target = root / safe_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(file.get("code", ""), encoding="utf-8")
        try:
            result = subprocess.run(
                [os.fspath(Path(os.sys.executable)), "-m", "pytest", "-q"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=30,
                env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.fspath(root)},
            )
            return jsonify({
                "status": "passed" if result.returncode == 0 else "failed",
                "exit_code": result.returncode,
                "output": (result.stdout + result.stderr)[-8000:],
            })
        except subprocess.TimeoutExpired:
            return jsonify({"status": "timeout", "message": "Tests exceeded the 30 second limit."}), 408


@app.route("/repo/<repo_id>")
def repo_view(repo_id):
    repo = REPOS.get(repo_id)
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


# ========= XỬ LÝ FOLDER LOCAL (/generate) =========

@app.route("/generate", methods=["POST"])
def generate():
    """
    Nhận folder code:
        JSON: { files: { path: content }, repo_name?: str, repo_path?: str }

    Phân tích từng file, merge DOT, review repo, lưu vào REPOS[repo_id].
    """
    data = request.get_json() or {}
    files = data.get("files")
    repo_name = data.get("repo_name", "Local repo")
    repo_path = data.get("repo_path", "Local folder")

    # 1) Không có trường "files" trong request (client gửi sai format)
    if files is None:
        return jsonify({"error": "Không nhận được dữ liệu files từ client."}), 400

    # 2) Có "files" nhưng là object rỗng -> folder rỗng
    if isinstance(files, dict) and len(files) == 0:
        return jsonify({"error": "Folder bạn chọn đang rỗng, không có file nào."}), 400

    # Giới hạn dung lượng folder
    total_size_bytes = sum(len(content.encode("utf-8")) for content in files.values())
    total_kb = total_size_bytes / 1024
    if total_kb > 100:
        return jsonify({
            "error": (
                f"Folder quá lớn ({total_kb:.2f} KB). "
                f"Vui lòng chọn folder nhỏ hơn 100KB."
            )
        }), 400

    allowed_ext = (".py", ".html", ".css", ".js")
    valid_files = {
        name: content
        for name, content in files.items()
        if name.lower().endswith(allowed_ext)
    }

    if not valid_files:
        return jsonify({
            "error": "No valid code files (.py, .html, .css, .js) found"
        }), 400

    dot_results: Dict[str, str] = {}
    file_infos: Dict[str, Dict] = {}
    errors: Dict[str, str] = {}

    for filename, code in valid_files.items():
        result, err = send_to_gemini(filename, code)
        if err:
            file_infos[filename] = {
                "path": filename,
                "status": "error",
                "error": err,
            }
            errors[filename] = err
        else:
            dot_code = result["dot_code"]
            dot_results[filename] = dot_code
            file_infos[filename] = {
                "path": filename,
                "status": "success",
                "dot_code": dot_code,
                "classes": result.get("classes", []),
                "functions": result.get("functions", []),
                "imports": result.get("imports", []),
                "description": result.get("description", ""),
            }

    if not dot_results:
        repo_id = str(uuid.uuid4())
        REPOS[repo_id] = {
            "files": file_infos,
            "summary": {
                "processed": 0,
                "failed": len(errors),
            },
            "diagram_svg": None,
            "dot_code": None,
            "name": repo_name,
            "path": repo_path,
            "review": None,
            "review_error": "All files failed to process.",
            "source": "local",
        }
        return jsonify({
            "error": "All files failed to process.",
            "details": errors,
        }), 500

    merged_dot = merge_dot_graphs(dot_results.values())
    svg_data, graphviz_error = render_svg_from_dot(merged_dot)

    # Review toàn repo
    review, review_err = review_repo_with_gemini(valid_files)

    repo_id = str(uuid.uuid4())
    REPOS[repo_id] = {
        "files": file_infos,
        "summary": {
            "processed": len(dot_results),
            "failed": len(errors),
        },
        "diagram_svg": svg_data,
        "dot_code": merged_dot,
        "name": repo_name,
        "path": repo_path,
        "review": review if review and not review_err else None,
        "review_error": review_err or graphviz_error,
        "source": "local",
    }

    return jsonify({
        "repo_id": repo_id,
        "summary": REPOS[repo_id]["summary"],
        "has_review": bool(review and not review_err),
        "graphviz_error": graphviz_error,
        "repo_name": repo_name,
        "repo_path": repo_path,
        "source": "local",
    })


# ========= XỬ LÝ GIT REPO (/add_git_repo) =========

@app.route("/add_git_repo", methods=["POST"])
def add_git_repo():
    """
    Nhận JSON: { git_url: str }
    Clone repo về, đọc file, rồi dùng chung logic phân tích như /generate.
    """
    data = request.get_json() or {}
    git_url = data.get("git_url", "").strip()

    if not git_url:
        return jsonify({"error": "git_url is required"}), 400

    files, clone_error = clone_git_repo_and_load_files(git_url)
    if clone_error:
        return jsonify({"error": clone_error}), 400

    # Tên repo từ URL
    repo_name = git_url.rstrip("/").split("/")[-1]
    if repo_name.endswith(".git"):
        repo_name = repo_name[:-4]
    repo_path = git_url

    # Giới hạn dung lượng (theo logic giống /generate)
    total_size_bytes = sum(len(content.encode("utf-8")) for content in files.values())
    total_kb = total_size_bytes / 1024
    if total_kb > 100:
        return jsonify({
            "error": (
                f"Git repo quá lớn ({total_kb:.2f} KB) theo giới hạn 100KB của demo."
            )
        }), 400

    allowed_ext = (".py", ".html", ".css", ".js")
    valid_files = {
        name: content
        for name, content in files.items()
        if name.lower().endswith(allowed_ext)
    }

    if not valid_files:
        return jsonify({
            "error": "No valid code files (.py, .html, .css, .js) found in git repo"
        }), 400

    dot_results: Dict[str, str] = {}
    file_infos: Dict[str, Dict] = {}
    errors: Dict[str, str] = {}

    for filename, code in valid_files.items():
        result, err = send_to_gemini(filename, code)
        if err:
            file_infos[filename] = {
                "path": filename,
                "status": "error",
                "error": err,
            }
            errors[filename] = err
        else:
            dot_code = result["dot_code"]
            dot_results[filename] = dot_code
            file_infos[filename] = {
                "path": filename,
                "status": "success",
                "dot_code": dot_code,
                "classes": result.get("classes", []),
                "functions": result.get("functions", []),
                "imports": result.get("imports", []),
                "description": result.get("description", ""),
            }

    if not dot_results:
        repo_id = str(uuid.uuid4())
        REPOS[repo_id] = {
            "files": file_infos,
            "summary": {
                "processed": 0,
                "failed": len(errors),
            },
            "diagram_svg": None,
            "dot_code": None,
            "name": repo_name,
            "path": repo_path,
            "review": None,
            "review_error": "All files failed to process from git repo.",
            "source": "git",
        }
        return jsonify({
            "error": "All files failed to process from git repo.",
            "details": errors,
        }), 500

    merged_dot = merge_dot_graphs(dot_results.values())
    svg_data, graphviz_error = render_svg_from_dot(merged_dot)

    review, review_err = review_repo_with_gemini(valid_files)

    repo_id = str(uuid.uuid4())
    REPOS[repo_id] = {
        "files": file_infos,
        "summary": {
            "processed": len(dot_results),
            "failed": len(errors),
        },
        "diagram_svg": svg_data,
        "dot_code": merged_dot,
        "name": repo_name,
        "path": repo_path,
        "review": review if review and not review_err else None,
        "review_error": review_err or graphviz_error,
        "source": "git",
    }

    return jsonify({
        "repo_id": repo_id,
        "summary": REPOS[repo_id]["summary"],
        "has_review": bool(review and not review_err),
        "graphviz_error": graphviz_error,
        "repo_name": repo_name,
        "repo_path": repo_path,
        "source": "git",
    })


# ========= AI CHAT CHO REPO – DÙNG CHUNG GEMINI_API_URL =========

def chat_about_repo_with_gemini(repo: Dict, question: str, history: List[Dict]):
    """
    Gọi Gemini (REST) để trả lời câu hỏi về 1 repo cụ thể.
    - repo: object REPOS[repo_id]
    - question: câu hỏi mới của user
    - history: [{role: "user"/"assistant", content: str}, ...]

    Trả về (answer, error)
    """
    try:
        context_parts = []

        # 1) Review chi tiết (nếu có)
        if repo.get("review"):
            context_parts.append("AI review summary for this repo:\n" + str(repo["review"]))

        # 2) Summary ngắn
        summary = repo.get("summary") or {}
        context_parts.append(
            "Repo summary: processed {processed} files, failed {failed} files.".format(
                processed=summary.get("processed", 0),
                failed=summary.get("failed", 0),
            )
        )

        # 3) Danh sách file chính
        files_dict = repo.get("files", {})
        file_names = list(files_dict.keys())
        if file_names:
            context_parts.append(
                "Main files in this repo:\n" +
                "\n".join(f"- {name}" for name in file_names[:50])
            )

        system_instr = (
            "You are a senior software engineer who deeply understands this code repository. "
            "Use the provided context about the project (review notes, summary, file list) to answer user questions. "
            "Focus on concrete, practical suggestions for improvements: architecture, readability, testing, "
            "performance, security, and maintainability. If something is not explicitly in the context, "
            "say that clearly and answer using general best practices.\n\n"
            "Repository context:\n"
            + "\n\n".join(context_parts)
        )

        contents = []

        # System context như một message user đầu tiên
        contents.append({
            "role": "user",
            "parts": [{"text": system_instr}],
        })

        # History
        for turn in history:
            text = (turn.get("content") or "").strip()
            if not text:
                continue
            role = turn.get("role")
            g_role = "user" if role == "user" else "model"
            contents.append({
                "role": g_role,
                "parts": [{"text": text}],
            })

        # Câu hỏi mới
        contents.append({
            "role": "user",
            "parts": [{"text": question}],
        })

        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.4,
                "topP": 0.9,
                "maxOutputTokens": 1024,
            },
        }

        resp, api_error = post_gemini(body, label="repo chat", timeout=60)
        if api_error or resp is None:
            return None, api_error

        data = resp.json()
        candidates = data.get("candidates")
        if not candidates:
            return None, "No candidates returned from Gemini"

        first = candidates[0]
        content = first.get("content", {})
        parts = content.get("parts", [])

        # Gộp mọi phần text lại, nhưng luôn cast sang str để tránh lỗi type
        answer_chunks: List[str] = []
        for p in parts:
            if isinstance(p, dict) and "text" in p:
                answer_chunks.append(str(p["text"]))

        answer_text = "".join(answer_chunks).strip()
        if not answer_text:
            # fallback: debug nhẹ
            return None, f"Empty response text from Gemini. Raw: {data}"

        return answer_text, None

    except Exception as e:
        # Log chi tiết ra console
        print("Gemini chat error:", repr(e))
        return None, str(e)



@app.route("/api/repo/<repo_id>/chat", methods=["POST"])
def api_repo_chat(repo_id):
    """
    API chat AI cho 1 repo cụ thể.

    Body JSON:
    {
      "question": "string",
      "history": [
        { "role": "user"|"assistant", "content": "..." },
        ...
      ]
    }
    """
    repo = REPOS.get(repo_id)
    if not repo:
        return jsonify({"error": "repo not found"}), 404

    data = request.get_json() or {}
    question = (data.get("question") or "").strip()
    history = data.get("history") or []

    if not question:
        return jsonify({"error": "Missing question"}), 400

    answer, err = chat_about_repo_with_gemini(repo, question, history)
    if err or not answer:
        return jsonify({"error": "AI chat failed", "detail": err}), 500

    return jsonify({"answer": answer})



# ========= API PHỤ: structure/file/graph/review/delete =========

@app.route("/api/repo/<repo_id>/structure", methods=["GET"])
def api_structure(repo_id):
    repo = REPOS.get(repo_id)
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


@app.route("/api/repo/<repo_id>/file/<path:file_path>", methods=["GET"])
def api_file(repo_id, file_path):
    repo = REPOS.get(repo_id)
    if not repo:
        return jsonify({"error": "repo not found"}), 404

    info = repo.get("files", {}).get(file_path)
    if not info:
        return jsonify({"error": "file not found"}), 404
    return jsonify(info)


@app.route("/api/repo/<repo_id>/graph", methods=["GET"])
def api_graph(repo_id):
    repo = REPOS.get(repo_id)
    if not repo:
        return jsonify({"error": "repo not found"}), 404

    svg_data = repo.get("diagram_svg")
    if not svg_data:
        return jsonify({
            "error": "no diagram",
            "graphviz_error": repo.get("review_error"),
        }), 404
    return jsonify({"diagram": svg_data})


@app.route("/api/repo/<repo_id>/review", methods=["GET"])
def api_repo_review(repo_id):
    repo = REPOS.get(repo_id)
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


@app.route("/api/repo/<repo_id>", methods=["DELETE"])
def api_delete_repo(repo_id):
    if repo_id in REPOS:
        del REPOS[repo_id]
        return jsonify({"status": "deleted"})
    return jsonify({"error": "repo not found"}), 404


if __name__ == "__main__":
    app.run(debug=True)
