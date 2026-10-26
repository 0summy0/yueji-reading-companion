from __future__ import annotations

import io
from pathlib import Path
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("YUEJI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("YUEJI_DATABASE", "test.sqlite3")
    monkeypatch.setenv("YUEJI_SEED_SAMPLES", "false")
    monkeypatch.setenv("YUEJI_AUTH_REQUIRED", "false")
    with TestClient(app) as test_client:
        yield test_client


def import_txt(client: TestClient, content: str = "第一段。\n\n第二段。\n\n第三段。", filename: str = "测试书.txt", title: str = "测试书"):
    response = client.post(
        "/api/books/import",
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
        data={"title": title, "author": "原创测试作者"},
    )
    assert response.status_code == 201, response.text
    return response.json()["book"]


def make_epub(*, script: bool = False, large: bool = False) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '''<?xml version="1.0" encoding="utf-8"?>
            <package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
              <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>顺序样书</dc:title><dc:creator>测试作者</dc:creator></metadata>
              <manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/><item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/></manifest>
              <spine><itemref idref="c2"/><itemref idref="c1"/></spine>
            </package>''',
        )
        body1 = "甲" * (2 * 1024 * 1024) if large else "后一章的第一段。"
        script_tag = "<script>alert(1)</script>" if script else ""
        archive.writestr("OEBPS/c1.xhtml", f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>后一章</h1><p>{body1}</p>{script_tag}</body></html>')
        archive.writestr("OEBPS/c2.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>先读章</h1><p>先读章的第一段。</p><p>先读章的第二段。</p></body></html>')
    return output.getvalue()
