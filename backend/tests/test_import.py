from __future__ import annotations

import io
import zipfile

import pytest

from app.importer import BookImportError, MAX_UPLOAD_BYTES, parse_book
from conftest import import_txt, make_epub


def passages(client, book_id):
    response = client.get(f"/api/books/{book_id}/passages")
    assert response.status_code == 200
    return response.json()["items"]


def test_txt_heading_without_blank_line_preserves_body(client):
    book = import_txt(client, "第一章 起点\n正文第一段。\n正文第二段。\n\n第二章 后来\n第三段。", "single-lines.txt")
    items = passages(client, book["id"])
    assert [item["chapter_title"] for item in items] == ["第一章 起点", "第二章 后来"]
    assert "正文第一段。" in items[0]["text"] and "正文第二段。" in items[0]["text"]
    assert items[1]["text"] == "第三段。"


def test_import_deduplicates_and_keeps_stable_ids_offsets(client):
    first = import_txt(client)
    items = passages(client, first["id"])
    assert [item["position"] for item in items] == [0, 1, 2]
    assert items[1]["start_char"] == items[0]["end_char"] + 2
    assert items[1]["id"] == items[1]["id"]
    duplicate = client.post(
        "/api/books/import", files={"file": ("测试书.txt", "第一段。\n\n第二段。\n\n第三段。".encode(), "text/plain")}
    )
    assert duplicate.status_code == 201
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["book"]["edition_id"] == first["edition_id"]
    assert [item["id"] for item in passages(client, first["id"])] == [item["id"] for item in items]
    assert len(client.get("/api/books").json()["items"]) == 1


def test_epub_follows_spine_not_manifest_order(client):
    response = client.post(
        "/api/books/import", files={"file": ("ordered.epub", make_epub(), "application/epub+zip")}
    )
    assert response.status_code == 201, response.text
    book = response.json()["book"]
    items = passages(client, book["id"])
    assert [item["text"] for item in items] == ["先读章的第一段。", "先读章的第二段。", "后一章的第一段。"]
    assert [item["chapter_order"] for item in items] == [1, 1, 2]
    assert items[0]["start_char"] == 0


def test_rejects_bad_txt_encoding_mime_and_oversize(client):
    invalid = client.post("/api/books/import", files={"file": ("bad.txt", b"\xff\xfe\x00", "text/plain")})
    assert invalid.status_code == 400
    wrong_mime = client.post("/api/books/import", files={"file": ("ok.txt", b"text", "text/html")})
    assert wrong_mime.status_code == 400
    with pytest.raises(BookImportError, match="20 MiB"):
        parse_book(b"a" * (MAX_UPLOAD_BYTES + 1), "huge.txt")


def test_rejects_zip_path_traversal_script_and_compression_bomb(client):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("../outside.txt", "bad")
    traversal = client.post(
        "/api/books/import", files={"file": ("traversal.epub", output.getvalue(), "application/epub+zip")}
    )
    assert traversal.status_code == 400
    assert "路径" in traversal.json()["detail"]

    scripted = client.post(
        "/api/books/import", files={"file": ("script.epub", make_epub(script=True), "application/epub+zip")}
    )
    assert scripted.status_code == 400
    assert "脚本" in scripted.json()["detail"]

    bomb = client.post(
        "/api/books/import", files={"file": ("bomb.epub", make_epub(large=True), "application/epub+zip")}
    )
    assert bomb.status_code == 400
    assert "压缩比" in bomb.json()["detail"]


def test_three_original_samples_have_distinct_spines(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "samples"))
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "true")
    monkeypatch.setenv("YUEJI_AUTH_REQUIRED", "false")
    with TestClient(app) as sample_client:
        books = sample_client.get("/api/books").json()["items"]
        assert len(books) == 3
        assert len({book["title"] for book in books}) == 3
        assert len({book["spine_style"]["color"] for book in books}) == 3
        assert len({(book["spine_style"]["height"], book["spine_style"]["width"]) for book in books}) == 3
