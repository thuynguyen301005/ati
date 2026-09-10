import json
import re
from typing import Any, Dict, Tuple

import requests

from config import GOOGLE_GEMINI_API_KEY

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"gemini-2.0-flash:generateContent?key={GOOGLE_GEMINI_API_KEY}"
)

STAGES = [
    ("stories", "User stories", "user stories, acceptance criteria, and assumptions"),
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
    passed = sum(check["passed"] for check in checks)
    return {"passed": passed == len(checks), "score": f"{passed}/{len(checks)}", "checks": checks}


def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("AI response did not contain a JSON object")
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("AI response must be a JSON object")
    return value


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
- For tasks, content must include tasks (array), where each task has id, title, description, and depends_on.
"""
    try:
        response = requests.post(
            GEMINI_API_URL,
            headers={"Content-Type": "application/json"},
            json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
            timeout=120,
        )
        if response.status_code != 200:
            return None, f"Gemini API error {response.status_code}: {response.text}"
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return _parse_json(text), None
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
