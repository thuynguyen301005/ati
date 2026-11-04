import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile
from typing import Any, Dict


def _safe_generated_path(path: str) -> Path | None:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    candidate = Path(normalized)
    if not normalized or ".." in candidate.parts:
        return None
    return candidate


def build_project_archive(project: Dict[str, Any]) -> io.BytesIO:
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
    return archive


def run_project_tests(project: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
    code_files = project["artifacts"].get("code", {}).get("content", {}).get("files", [])
    test_files = project["artifacts"].get("tests", {}).get("content", {}).get("files", [])
    python_files = [
        file for file in code_files + test_files if file.get("path", "").endswith(".py")
    ]
    if not python_files:
        return {"status": "skipped", "message": "No Python tests were generated."}, 200

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
            return {
                "status": "passed" if result.returncode == 0 else "failed",
                "exit_code": result.returncode,
                "output": (result.stdout + result.stderr)[-8000:],
            }, 200
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "message": "Tests exceeded the 30 second limit.",
            }, 408
