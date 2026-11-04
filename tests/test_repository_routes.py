import pytest

from app import app
from web import repository_analysis_routes, state
from services import repository_analysis


@pytest.mark.parametrize(
    ("endpoint", "payload", "source", "expected_name", "expected_path"),
    [
        (
            "/generate",
            {
                "files": {"main.py": "print('hello')", "notes.txt": "ignored"},
                "repo_name": "Local project",
                "repo_path": "C:/projects/local",
            },
            "local",
            "Local project",
            "C:/projects/local",
        ),
        (
            "/add_git_repo",
            {"git_url": "https://example.com/team/project.git"},
            "git",
            "project",
            "https://example.com/team/project.git",
        ),
    ],
)
def test_repository_routes_use_shared_processing(
    monkeypatch, endpoint, payload, source, expected_name, expected_path
):
    stored_repositories = {}
    analyzed_files = []
    reviewed_files = []
    monkeypatch.setattr(state, "REPOS", stored_repositories)
    monkeypatch.setattr(
        repository_analysis,
        "send_to_gemini",
        lambda filename, code: (
            analyzed_files.append((filename, code))
            or (
                {
                    "dot_code": "digraph {}",
                    "classes": [],
                    "functions": [],
                    "imports": [],
                    "description": "",
                },
                None,
            )
        ),
    )
    monkeypatch.setattr(repository_analysis, "merge_dot_graphs", lambda graphs: "digraph {}")
    monkeypatch.setattr(
        repository_analysis, "render_svg_from_dot", lambda dot: ("<svg />", None)
    )
    monkeypatch.setattr(
        repository_analysis,
        "review_repo_with_gemini",
        lambda files: (reviewed_files.append(files) or {"summary": "ok"}, None),
    )
    monkeypatch.setattr(
        repository_analysis_routes,
        "clone_git_repo_and_load_files",
        lambda url: ({"main.py": "print('hello')", "notes.txt": "ignored"}, None),
    )

    response = app.test_client().post(endpoint, json=payload)

    assert response.status_code == 200
    result = response.get_json()
    assert result["source"] == source
    assert result["repo_name"] == expected_name
    assert result["repo_path"] == expected_path
    assert result["summary"] == {"processed": 1, "failed": 0}
    assert analyzed_files == [("main.py", "print('hello')")]
    assert reviewed_files == [{"main.py": "print('hello')"}]
    saved = stored_repositories[result["repo_id"]]
    assert saved["source"] == source
    assert saved["files"]["main.py"]["status"] == "success"


@pytest.mark.parametrize(
    ("endpoint", "payload", "source", "expected_error"),
    [
        (
            "/generate",
            {"files": {"main.py": "invalid"}},
            "local",
            "All files failed to process.",
        ),
        (
            "/add_git_repo",
            {"git_url": "https://example.com/team/project.git"},
            "git",
            "All files failed to process from git repo.",
        ),
    ],
)
def test_repository_routes_preserve_all_files_failed_response(
    monkeypatch, endpoint, payload, source, expected_error
):
    stored_repositories = {}
    monkeypatch.setattr(state, "REPOS", stored_repositories)
    monkeypatch.setattr(
        repository_analysis,
        "send_to_gemini",
        lambda filename, code: (None, "analysis failed"),
    )
    monkeypatch.setattr(
        repository_analysis_routes,
        "clone_git_repo_and_load_files",
        lambda url: ({"main.py": "invalid"}, None),
    )

    response = app.test_client().post(endpoint, json=payload)

    assert response.status_code == 500
    result = response.get_json()
    assert result == {
        "error": expected_error,
        "details": {"main.py": "analysis failed"},
    }
    saved = next(iter(stored_repositories.values()))
    assert saved["source"] == source
    assert saved["review_error"] == expected_error
    assert saved["summary"] == {"processed": 0, "failed": 1}
