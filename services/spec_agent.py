import json
from typing import Any, Dict, List, Tuple

from services.gemini_client import post_gemini
from services.json_utils import parse_json_loose

STAGES = [
    ("stories", "User stories", "user stories, acceptance criteria, and assumptions"),
    ("diagrams", "UML diagrams", "a UML use case diagram and an activity diagram, both as Graphviz DOT"),
    ("architecture", "Architecture", "a pragmatic system architecture and Graphviz DOT diagram"),
    ("tasks", "Implementation tasks", "an ordered implementation backlog with dependencies"),
    ("code", "Source code", "a small but coherent runnable MVP source tree"),
    ("tests", "Tests", "focused automated tests for the generated source tree"),
    ("docs", "Deployment docs", "README and deployment files for running the generated project"),
]


STAGE_KEYS = [stage[0] for stage in STAGES]


def validate_artifacts(artifacts: Dict[str, Any], stages: List[str]) -> Dict[str, Any]:
    """Run deterministic contract checks before exposing generated output."""
    checks = []
    for key in stages:
        present = key in artifacts and isinstance(artifacts[key], dict)
        checks.append({"name": f"{key} artifact exists", "passed": present})

    code_files = (artifacts.get("code", {}).get("content", {}) or {}).get("files", [])
    test_files = (artifacts.get("tests", {}).get("content", {}) or {}).get("files", [])
    if "code" in stages:
        checks.append({"name": "source code contains files", "passed": bool(code_files)})
    if "tests" in stages:
        checks.append({"name": "tests contain files", "passed": bool(test_files)})
    if "code" in stages or "tests" in stages:
        code_paths = {file.get("path") for file in code_files if isinstance(file, dict)}
        test_paths = {file.get("path") for file in test_files if isinstance(file, dict)}
        checks.append({
            "name": "generated paths are unique",
            "passed": len(code_paths) == len(code_files) and len(test_paths) == len(test_files),
        })
    if "diagrams" in stages:
        diagrams = (artifacts.get("diagrams", {}).get("content", {}) or {})
        for name in ("use_case", "activity"):
            block = diagrams.get(name) or {}
            dot_code = block.get("dot_code") if isinstance(block, dict) else None
            checks.append({
                "name": f"{name} diagram has DOT source",
                "passed": bool(dot_code and "digraph" in str(dot_code)),
            })

    passed = sum(check["passed"] for check in checks)
    return {"passed": passed == len(checks), "score": f"{passed}/{len(checks)}", "checks": checks}


ARTIFACT_RULES = """Rules:
- Keep the output practical and implementation-ready.
- Preserve decisions from previous artifacts; do not invent conflicting requirements.
- Do not include Markdown fences outside string values.
- For source code, content.files must be an array of {"path": "...", "language": "...", "code": "..."}.
- For tests and docs, use the same content.files format.
- For architecture, content must include components (array), decisions (array), and dot_code (a valid digraph string).
- For stories, content must include stories (array) and assumptions (array).
- For diagrams, content must include use_case and activity objects:
  "use_case": {
    "actors": [{"name": "...", "description": "..."}],
    "use_cases": [{"id": "UC1", "name": "...", "actors": ["..."], "description": "..."}],
    "dot_code": "digraph UseCase { rankdir=LR; ... }"
  },
  "activity": {
    "scenario": "name of the main flow being modelled",
    "steps": [{"id": "A1", "name": "...", "type": "start|action|decision|end", "next": ["A2"]}],
    "dot_code": "digraph Activity { rankdir=TB; ... }"
  }
- Use case DOT style: actors as node [shape=box, style=rounded] outside a
  "subgraph cluster_system" that holds the use cases as node [shape=ellipse];
  associations are plain edges actor -> use case (edge [arrowhead=none]);
  use "style=dashed, label=\"<<include>>\"" for include/extend edges.
- Activity DOT style: start and end as node [shape=circle, label=""] (end uses
  peripheries=2), actions as node [shape=box, style=rounded], decisions as
  node [shape=diamond] with labelled outgoing edges (yes/no).
- Every dot_code must be one self-contained digraph that renders in Graphviz:
  quote every label, never leave an edge pointing at an undeclared node.
- For tasks, content must include tasks (array), where each task has id, title, description, and depends_on.
"""


def _ask_agent(requirement: str, context: str, stage_name: str, deliverable: str) -> Tuple[Dict[str, Any] | None, str | None]:
    prompt = f"""You are a senior software architect and implementation agent.
Convert the user's specification into a concrete, internally consistent software artifact.

USER SPECIFICATION:
{requirement}

PREVIOUS ARTIFACTS:
{context or "None yet."}

CURRENT STAGE: {stage_name}
DELIVERABLE: {deliverable}

Return valid JSON only, with this exact envelope:
{{
  "title": "short artifact title",
  "summary": "brief useful summary",
  "content": {{}}
}}

{ARTIFACT_RULES}"""
    return _call_json(prompt, stage_name)


def _call_json(prompt: str, label: str) -> Tuple[Dict[str, Any] | None, str | None]:
    response, error = post_gemini(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            # Ep model tra ve JSON thuan, khong kem fence hay loi dan.
            "generationConfig": {"responseMimeType": "application/json"},
        },
        label=label,
    )
    if error or response is None:
        return None, error
    try:
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return parse_json_loose(text), None
    except Exception as exc:
        return None, str(exc)


def generate_software_plan(
    requirement: str, stages: List[str] | None = None
) -> Tuple[Dict[str, Any] | None, str | None]:
    """Chi chay cac stage duoc chon, giu thu tu goc cua pipeline."""
    selected = [key for key in STAGE_KEYS if not stages or key in stages]
    artifacts: Dict[str, Any] = {}
    context_parts = []

    for key, stage_name, deliverable in STAGES:
        if key not in selected:
            continue
        artifact, error = _ask_agent(
            requirement,
            "\n\n".join(context_parts),
            stage_name,
            deliverable,
        )
        if error or not artifact:
            return None, f"Stage '{stage_name}' failed: {error}"
        artifacts[key] = artifact
        context_parts.append(f"[{stage_name}]\n{json.dumps(artifact, ensure_ascii=True)}")

    return {
        "requirement": requirement,
        "artifacts": artifacts,
        "stages": selected,
        "validation": validate_artifacts(artifacts, selected),
    }, None


# So tin nhan gan nhat dua vao prompt, tranh prompt phinh to qua.
CHAT_HISTORY_LIMIT = 20


def revise_project(project: Dict[str, Any], message: str) -> Tuple[Dict[str, Any] | None, str | None]:
    """
    Chat tiep tren mot project da tao: tra ve {"reply": str, "updates": {key: artifact}}.
    Chi artifact can doi moi nam trong updates, va moi artifact la ban day du.
    """
    stage_list = "\n".join(f"- {key}: {name} ({deliverable})" for key, name, deliverable in STAGES)
    history = "\n".join(
        f"{item['role'].upper()}: {item['content']}"
        for item in (project.get("messages") or [])[-CHAT_HISTORY_LIMIT:]
    )
    prompt = f"""You are a senior software architect and implementation agent.
You already produced the software artifacts below for the user's specification.
The user is now chatting with you to refine them.

ORIGINAL SPECIFICATION:
{project.get("requirement", "")}

CURRENT ARTIFACTS (JSON, keyed by stage):
{json.dumps(project.get("artifacts", {}), ensure_ascii=True)}

AVAILABLE STAGES:
{stage_list}

CONVERSATION SO FAR:
{history or "None yet."}

NEW USER MESSAGE:
{message}

Decide what the user wants:
- If they ask a question, answer it and leave updates empty.
- If they ask for a change, rewrite every artifact affected by it so all artifacts stay
  consistent (for example a new feature may touch stories, diagrams, architecture, tasks,
  code, tests, and docs). A stage that does not exist yet may be added if asked for.
- Never return an artifact that did not change.

Reply in the same language the user writes in.

Return valid JSON only, with this exact envelope:
{{
  "reply": "short message to the user explaining what you answered or changed",
  "updates": {{
    "<stage key>": {{"title": "...", "summary": "...", "content": {{}}}}
  }}
}}

Each artifact in updates must be the complete new version, following these rules:
{ARTIFACT_RULES}"""
    result, error = _call_json(prompt, "chat")
    if error or not isinstance(result, dict):
        return None, error or "Invalid response from the agent."

    updates = {}
    for key, artifact in (result.get("updates") or {}).items():
        if key in STAGE_KEYS and isinstance(artifact, dict) and isinstance(artifact.get("content"), dict):
            updates[key] = artifact
    return {"reply": str(result.get("reply") or "Done."), "updates": updates}, None
