from fastapi.testclient import TestClient


def test_public_stats_requires_no_auth_and_excludes_word_text(client: TestClient, auth_headers: dict) -> None:
    client.post(
        "/words",
        json={"word": "gut", "type": "adjektiv", "meaning": "good", "is_hard": True},
        headers=auth_headers,
    )

    resp = client.get("/public/stats")
    assert resp.status_code == 200
    body = resp.json()

    assert body["total_words"] == 1
    assert body["hard_to_remember"] == 1
    assert body["by_type"]["adjektiv"] == 1
    assert body["by_type"]["verb"] == 0
    assert len(body["added_last_30_days"]) == 30

    assert "gut" not in resp.text
