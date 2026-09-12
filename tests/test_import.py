import json

from fastapi.testclient import TestClient


def _preview(client: TestClient, headers: dict, content: bytes, filename: str = "words.csv"):
    return client.post(
        "/import/preview",
        files={"file": (filename, content, "text/csv")},
        headers=headers,
    )


def _commit(client: TestClient, headers: dict, content: bytes, mapping: dict, policy: str, filename: str = "words.csv"):
    return client.post(
        "/import/commit",
        files={"file": (filename, content, "text/csv")},
        data={"mapping": json.dumps(mapping), "policy": policy},
        headers=headers,
    )


def test_cp1252_semicolon_csv_umlauts_intact(client: TestClient, auth_headers: dict) -> None:
    text = "Wort;Art;Bedeutung\r\nÜbung;Adjektiv;exercise-ish\r\n"
    content = text.encode("cp1252")

    preview = _preview(client, auth_headers, content)
    assert preview.status_code == 200
    body = preview.json()
    assert body["encoding"] == "cp1252"
    assert body["delimiter"] == ";"
    assert body["suggested_mapping"] == {"word": "Wort", "type": "Art", "meaning": "Bedeutung"}
    assert body["sample"][0]["word"] == "Übung"

    commit = _commit(client, auth_headers, content, body["suggested_mapping"], "skip")
    assert commit.status_code == 200
    report = commit.json()
    assert report["inserted"] == 1
    assert report["errors"] == []

    words = client.get("/words", headers=auth_headers).json()
    assert any(w["word"] == "Übung" for w in words)


def test_utf8_comma_csv_imports_without_config(client: TestClient, auth_headers: dict) -> None:
    content = "word,type,meaning\nschnell,adjektiv,fast\n".encode()

    preview = _preview(client, auth_headers, content)
    assert preview.status_code == 200
    assert preview.json()["encoding"] in ("utf-8", "utf-8-sig")
    assert preview.json()["delimiter"] == ","

    commit = _commit(client, auth_headers, content, {"word": "word", "type": "type", "meaning": "meaning"}, "skip")
    assert commit.status_code == 200
    assert commit.json()["inserted"] == 1


def test_reimport_same_file_with_skip_policy_inserts_zero(client: TestClient, auth_headers: dict) -> None:
    content = "word,type,meaning\nschnell,adjektiv,fast\n".encode()
    mapping = {"word": "word", "type": "type", "meaning": "meaning"}

    first = _commit(client, auth_headers, content, mapping, "skip")
    assert first.json()["inserted"] == 1

    second = _commit(client, auth_headers, content, mapping, "skip")
    body = second.json()
    assert body["inserted"] == 0
    assert body["skipped"] == 1


def test_malformed_rows_reported_by_row_number_rest_imported(client: TestClient, auth_headers: dict) -> None:
    # 3 malformed rows out of 8 total (37.5%) stays under the 50% rollback
    # threshold, so the valid rows still commit.
    content = (
        "word,type,meaning\n"
        "schnell,adjektiv,fast\n"  # row 1: valid
        ",adjektiv,missing word\n"  # row 2: missing word
        "komisch,Nomenx,weird\n"  # row 3: unrecognized type
        "toll,adjektiv,\n"  # row 4: missing meaning
        "gut,adjektiv,good\n"  # row 5: valid
        "klein,adjektiv,small\n"  # row 6: valid
        "gross,adjektiv,big\n"  # row 7: valid
        "neu,adjektiv,new\n"  # row 8: valid
    ).encode()
    mapping = {"word": "word", "type": "type", "meaning": "meaning"}

    resp = _commit(client, auth_headers, content, mapping, "skip")
    body = resp.json()
    assert body["inserted"] == 5
    assert len(body["errors"]) == 3
    assert {e["row"] for e in body["errors"]} == {2, 3, 4}
