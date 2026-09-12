import json

from fastapi.testclient import TestClient


def test_export_then_reimport_is_noop(client: TestClient, auth_headers: dict) -> None:
    client.post(
        "/words",
        json={"word": "schnell", "type": "adjektiv", "meaning": "fast", "attrs": {"komparativ": "schneller"}},
        headers=auth_headers,
    )

    csv_export = client.get("/export?format=csv", headers=auth_headers)
    assert csv_export.status_code == 200
    assert "schnell" in csv_export.text

    commit = client.post(
        "/import/commit",
        files={"file": ("export.csv", csv_export.content, "text/csv")},
        data={
            "mapping": json.dumps({"word": "word", "type": "type", "meaning": "meaning", "example": "example", "tags": "tags", "source": "source"}),
            "policy": "skip",
        },
        headers=auth_headers,
    )
    body = commit.json()
    assert body["inserted"] == 0
    assert body["skipped"] == 1


def test_export_json_format(client: TestClient, auth_headers: dict) -> None:
    client.post(
        "/words",
        json={"word": "gut", "type": "adjektiv", "meaning": "good"},
        headers=auth_headers,
    )
    resp = client.get("/export?format=json", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert any(row["word"] == "gut" for row in data)
