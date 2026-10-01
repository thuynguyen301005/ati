import json
from typing import Any, Dict, Tuple

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


def validate_artifacts(artifacts: Dict[str, Any]) -> Dict[str, Any]:
    """Run deterministic contract checks before exposing generated output."""
    checks = []
    required_stages = [stage[0] for stage in STAGES]
    for key in required_stages:
        present = key in artifacts and isinstance(artifacts[key], dict)
        checks.append({"name": f"{key} artifact exists", "passed": present})

    code_files = (artifacts.get("code", {}).get("content", {}) or {}).get("files", [])
    test_files = (artifacts.get("tests", {}).get("content", {}) or {}).get("files", [])
    checks.append({"name": "source code contains files", "passed": bool(code_files)})
    checks.append({"name": "tests contain files", "passed": bool(test_files)})
    code_paths = {file.get("path") for file in code_files if isinstance(file, dict)}
    test_paths = {file.get("path") for file in test_files if isinstance(file, dict)}
    checks.append({
        "name": "generated paths are unique",
        "passed": len(code_paths) == len(code_files) and len(test_paths) == len(test_files),
    })
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

Rules:
- Keep the output practical and implementation-ready.
- Preserve decisions from previous artifacts; do not invent conflicting requirements.
- Do not include Markdown fences outside string values.
- For source code, content.files must be an array of {{"path": "...", "language": "...", "code": "..."}}.
- For tests and docs, use the same content.files format.
- For architecture, content must include components (array), decisions (array), and dot_code (a valid digraph string).
- For stories, content must include stories (array) and assumptions (array).
- For diagrams, content must include use_case and activity objects:
  "use_case": {{
    "actors": [{{"name": "...", "description": "..."}}],
    "use_cases": [{{"id": "UC1", "name": "...", "actors": ["..."], "description": "..."}}],
    "dot_code": "digraph UseCase {{ rankdir=LR; ... }}"
  }},
  "activity": {{
    "scenario": "name of the main flow being modelled",
    "steps": [{{"id": "A1", "name": "...", "type": "start|action|decision|end", "next": ["A2"]}}],
    "dot_code": "digraph Activity {{ rankdir=TB; ... }}"
  }}
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
    response, error = post_gemini(
        {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            # Ep model tra ve JSON thuan, khong kem fence hay loi dan.
            "generationConfig": {"responseMimeType": "application/json"},
        },
        label=stage_name,
    )
    if error or response is None:
        return None, error
    try:
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return parse_json_loose(text), None
    except Exception as exc:
        return None, str(exc)


def generate_software_plan(requirement: str) -> Tuple[Dict[str, Any] | None, str | None]:
    artifacts: Dict[str, Any] = {}
    context_parts = []

    for key, stage_name, deliverable in STAGES:
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
        "validation": validate_artifacts(artifacts),
    }, None
