from app import app
from services import specification_service
from web import specification_artifacts, specification_projects


def test_generate_specification_route_keeps_response_contract(monkeypatch):
    saved_projects = []
    monkeypatch.setattr(
        specification_service,
        "generate_software_plan",
        lambda requirement, stages: (
            {
                "requirement": requirement,
                "artifacts": {
                    "architecture": {
                        "title": "Architecture",
                        "content": {},
                    }
                },
            },
            None,
        ),
    )
    monkeypatch.setattr(
        specification_service.db,
        "save_project",
        lambda user_id, project: saved_projects.append((user_id, project.copy())),
    )

    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 42

    response = client.post(
        "/api/spec/generate",
        json={"requirement": "Build a small specification service"},
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["project_id"] == result["project"]["id"]
    assert result["project"]["title"] == "Architecture"
    assert len(result["project"]["messages"]) == 2
    assert saved_projects[0][0] == 42
    assert saved_projects[0][1]["id"] == result["project_id"]


def test_project_routes_keep_not_found_responses_before_body_validation(monkeypatch):
    monkeypatch.setattr(specification_projects, "get_project", lambda user_id, project_id: None)
    monkeypatch.setattr(specification_artifacts, "get_project", lambda user_id, project_id: None)
    client = app.test_client()
    with client.session_transaction() as session:
        session["user_id"] = 42

    rename = client.patch("/api/spec/missing", json={})
    chat = client.post("/api/spec/missing/chat", json={})
    artifact = client.put("/api/spec/missing/artifacts/code", json={})

    assert rename.status_code == 404
    assert rename.get_json() == {"error": "specification project not found"}
    assert chat.status_code == 404
    assert chat.get_json() == {"error": "specification project not found"}
    assert artifact.status_code == 404
    assert artifact.get_json() == {"error": "specification project not found"}
