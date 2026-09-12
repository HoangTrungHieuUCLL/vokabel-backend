from fastapi.testclient import TestClient


def test_healthz_no_auth_required(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_words_requires_auth(client: TestClient) -> None:
    resp = client.get("/words")
    assert resp.status_code == 401


def test_create_nomen_missing_artikel_rejected(client: TestClient, auth_headers: dict) -> None:
    resp = client.post(
        "/words",
        json={"word": "Haus", "type": "nomen", "meaning": "house", "attrs": {"plural": "Häuser"}},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "artikel" in resp.text


def test_create_verb_missing_required_rejected(client: TestClient, auth_headers: dict) -> None:
    resp = client.post(
        "/words",
        json={
            "word": "machen",
            "type": "verb",
            "meaning": "to do",
            "attrs": {"hilfsverb": "haben", "praesens_3sg": "macht"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "praeteritum" in resp.text


def test_create_rejects_unknown_attr_key(client: TestClient, auth_headers: dict) -> None:
    resp = client.post(
        "/words",
        json={
            "word": "schnell",
            "type": "adjektiv",
            "meaning": "fast",
            "attrs": {"komparativ": "schneller", "unbekannt": "x"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "unbekannt" in resp.text


def test_create_valid_nomen(client: TestClient, auth_headers: dict) -> None:
    resp = client.post(
        "/words",
        json={
            "word": "das Haus",
            "type": "nomen",
            "meaning": "house",
            "attrs": {"artikel": "das", "plural": "Häuser"},
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["search_key"] == "haus"
    assert body["attrs"] == {"artikel": "das", "plural": "Häuser"}


def test_duplicate_word_returns_409_with_existing(client: TestClient, auth_headers: dict) -> None:
    payload = {
        "word": "üben",
        "type": "verb",
        "meaning": "to practice",
        "attrs": {
            "hilfsverb": "haben",
            "praesens_3sg": "übt",
            "praeteritum": "übte",
            "partizip_ii": "geübt",
        },
    }
    first = client.post("/words", json=payload, headers=auth_headers)
    assert first.status_code == 201

    # "Üben" differs only by case -> same search_key ("ueben") and type as the first row
    second = client.post("/words", json={**payload, "word": "Üben"}, headers=auth_headers)
    assert second.status_code == 409
    assert second.json()["detail"]["existing"]["word"] == "üben"


def test_patch_recomputes_search_key(client: TestClient, auth_headers: dict) -> None:
    created = client.post(
        "/words",
        json={"word": "Hut", "type": "nomen", "meaning": "hat", "attrs": {"artikel": "der", "plural": "Hüte"}},
        headers=auth_headers,
    ).json()

    resp = client.patch(f"/words/{created['id']}", json={"word": "die Straße"}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["search_key"] == "strasse"


def test_patch_is_hard_sets_and_clears_hard_since(client: TestClient, auth_headers: dict) -> None:
    created = client.post(
        "/words",
        json={"word": "Katze", "type": "nomen", "meaning": "cat", "attrs": {"artikel": "die", "plural": "Katzen"}},
        headers=auth_headers,
    ).json()

    flagged = client.patch(f"/words/{created['id']}", json={"is_hard": True}, headers=auth_headers).json()
    assert flagged["is_hard"] is True
    assert flagged["hard_since"] is not None

    unflagged = client.patch(f"/words/{created['id']}", json={"is_hard": False}, headers=auth_headers).json()
    assert unflagged["is_hard"] is False
    assert unflagged["hard_since"] is None


def test_delete_is_soft(client: TestClient, auth_headers: dict) -> None:
    created = client.post(
        "/words",
        json={"word": "Buch", "type": "nomen", "meaning": "book", "attrs": {"artikel": "das", "plural": "Bücher"}},
        headers=auth_headers,
    ).json()

    resp = client.delete(f"/words/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204

    listed = client.get("/words", headers=auth_headers).json()
    assert all(w["id"] != created["id"] for w in listed)

    since = client.get("/words?updated_since=2020-01-01T00:00:00Z", headers=auth_headers).json()
    assert any(w["id"] == created["id"] and w["deleted_at"] is not None for w in since)


def test_bulk_create_never_fails_whole_batch(client: TestClient, auth_headers: dict) -> None:
    resp = client.post(
        "/words/bulk",
        json=[
            {"word": "gut", "type": "adjektiv", "meaning": "good"},
            {"word": "Haus", "type": "nomen", "meaning": "house"},  # missing required attrs
        ],
        headers=auth_headers,
    )
    assert resp.status_code == 200
    results = resp.json()
    assert results[0]["status"] == "created"
    assert results[1]["status"] == "error"
