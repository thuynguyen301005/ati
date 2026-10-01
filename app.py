from flask import Flask, render_template, request, jsonify, send_file
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile
import uuid
from typing import Dict, List
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
from services.spec_agent import generate_software_plan

app = Flask(__name__)

# Lưu nhiều repo: repo_id -> analysis result
REPOS: Dict[str, Dict] = {}
SPEC_PROJECTS: Dict[str, Dict] = {}


# ========= ROUTES CƠ BẢN =========

@app.route("/")
def home():
    return render_template("spec.html")


@app.route("/api/spec/generate", methods=["POST"])
def generate_specification():
    data = request.get_json() or {}
    requirement = (data.get("requirement") or "").strip()
    if len(requirement) < 20:
        return jsonify({"error": "Requirement must contain at least 20 characters."}), 400
    if len(requirement) > 12000:
        return jsonify({"error": "Requirement is too large. Keep it under 12,000 characters."}), 400

    project, error = generate_software_plan(requirement)
    if error or not project:
        return jsonify({"error": error or "Unable to generate the software plan."}), 502

    project_id = str(uuid.uuid4())
    project["id"] = project_id
    architecture = project["artifacts"].get("architecture", {}).get("content", {})
    dot_code = architecture.get("dot_code")
    if dot_code:
        project["architecture_svg"], project["architecture_error"] = render_svg_from_dot(dot_code)

    # Use case + activity diagram: render san SVG de frontend chi viec nhung vao.
    diagrams = project["artifacts"].get("diagrams", {}).get("content", {}) or {}
    project["diagram_svgs"] = {}
    project["diagram_errors"] = {}
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
    SPEC_PROJECTS[project_id] = project
    return jsonify({"project_id": project_id, "project": project})


@app.route("/api/spec/<project_id>", methods=["GET"])
def get_specification(project_id):
    project = SPEC_PROJECTS.get(project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404
    return jsonify({"project": project})


def _safe_generated_path(path: str) -> Path | None:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    candidate = Path(normalized)
    if not normalized or ".." in candidate.parts:
        return None
    return candidate


@app.route("/api/spec/<project_id>/export", methods=["GET"])
def export_specification(project_id):
    project = SPEC_PROJECTS.get(project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404

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
def run_generated_tests(project_id):
    project = SPEC_PROJECTS.get(project_id)
    if not project:
        return jsonify({"error": "specification project not found"}), 404

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
