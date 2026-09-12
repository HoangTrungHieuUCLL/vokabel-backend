import os

from fastapi.testclient import TestClient

from tests.conftest import TEST_PASSWORD


def test_login_success(client: TestClient) -> None:
    resp = client.post(
        "/auth/login",
        json={"username": os.environ["APP_USERNAME"], "password": TEST_PASSWORD},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


def test_login_wrong_password(client: TestClient) -> None:
    resp = client.post(
        "/auth/login",
        json={"username": os.environ["APP_USERNAME"], "password": "wrong"},
    )
    assert resp.status_code == 401


def test_me_requires_valid_token(client: TestClient, auth_headers: dict) -> None:
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == os.environ["APP_USERNAME"]

    resp_no_auth = client.get("/auth/me")
    assert resp_no_auth.status_code == 401
