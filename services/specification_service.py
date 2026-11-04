from datetime import datetime, timezone
from typing import Any, Dict, List
import uuid

from services import db
from services.analysis import render_svg_from_dot
from services.spec_agent import (
    STAGES,
    STAGE_KEYS,
    generate_software_plan,
    revise_project,
    validate_artifacts,
)


STAGE_NAMES = {key: name for key, name, _ in STAGES}
MAX_CHAT_MESSAGE_CHARS = 4000


def render_project_diagrams(project: Dict[str, Any]) -> None:
    """Render SVGs for architecture, use-case, and activity diagrams."""
    architecture = project["artifacts"].get("architecture", {}).get("content", {}) or {}
    dot_code = architecture.get("dot_code") if isinstance(architecture, dict) else None
    project["architecture_svg"], project["architecture_error"] = (
        render_svg_from_dot(dot_code) if dot_code else (None, None)
    )

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


def project_title(project: Dict[str, Any]) -> str:
    first = next(iter(project["artifacts"].values()), {})
    title = (first.get("title") if isinstance(first, dict) else None) or project["requirement"][:60]
    return str(title).strip()[:120] or "Untitled project"


def chat_message(
    role: str,
    content: str,
    updated: List[str] | None = None,
) -> Dict[str, Any]:
    message = {
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if updated:
        message["updated"] = updated
    return message


def create_project(
    user_id: int,
    requirement: str,
    stages: List[str] | None,
) -> tuple[Dict[str, Any] | None, str | None]:
    project, error = generate_software_plan(requirement, stages)
    if error or not project:
        return None, error or "Unable to generate the software plan."

    project["id"] = str(uuid.uuid4())
    project["title"] = project_title(project)
    render_project_diagrams(project)
    generated = list(project["artifacts"])
    project["messages"] = [
        chat_message("user", requirement),
        chat_message(
            "assistant",
            "Generated " + ", ".join(STAGE_NAMES[key] for key in generated)
            + ". Tell me what to change and I will update the documents.",
            generated,
        ),
    ]
    db.save_project(user_id, project)
    return project, None


def get_project(user_id: int, project_id: str) -> Dict[str, Any] | None:
    return db.get_project(user_id, project_id)


def list_projects(user_id: int) -> List[Dict[str, Any]]:
    return db.list_projects(user_id)


def rename_project(
    user_id: int,
    project: Dict[str, Any],
    title: str,
) -> Dict[str, Any]:
    project["title"] = title[:120]
    db.save_project(user_id, project)
    return project


def delete_project(user_id: int, project_id: str) -> bool:
    return db.delete_project(user_id, project_id)


def revise_saved_project(
    user_id: int,
    project: Dict[str, Any],
    message: str,
) -> tuple[Dict[str, Any] | None, str | None, List[str], str | None]:
    result, error = revise_project(project, message)
    if error or not result:
        return None, None, [], error or "The agent could not answer."

    updates = result["updates"]
    for key, artifact in updates.items():
        project["artifacts"][key] = {
            "title": str(artifact.get("title") or STAGE_NAMES[key]),
            "summary": str(artifact.get("summary") or ""),
            "content": artifact["content"],
        }
    project["artifacts"] = {
        key: project["artifacts"][key]
        for key in STAGE_KEYS
        if key in project["artifacts"]
    }
    project["stages"] = list(project["artifacts"])
    if "architecture" in updates or "diagrams" in updates:
        render_project_diagrams(project)
    project["validation"] = validate_artifacts(project["artifacts"], project["stages"])

    messages = project.setdefault("messages", [])
    messages.append(chat_message("user", message))
    messages.append(chat_message("assistant", result["reply"], list(updates)))
    db.save_project(user_id, project)
    return project, result["reply"], list(updates), None


def update_project_artifact(
    user_id: int,
    project: Dict[str, Any],
    key: str,
    artifact: Dict[str, Any],
) -> Dict[str, Any]:
    project["artifacts"][key] = {
        "title": str(artifact.get("title") or "").strip() or key,
        "summary": str(artifact.get("summary") or ""),
        "content": artifact["content"],
    }
    if key in ("architecture", "diagrams"):
        render_project_diagrams(project)
    stages = project.get("stages") or list(project["artifacts"])
    project["validation"] = validate_artifacts(project["artifacts"], stages)
    db.save_project(user_id, project)
    return project
