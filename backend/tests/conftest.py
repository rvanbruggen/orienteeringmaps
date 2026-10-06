import importlib
import io

import pytest
from PIL import Image


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OMAPS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OMAPS_FRONTEND_DIST", str(tmp_path / "no-dist"))
    from app import config
    importlib.reload(config)
    from app import main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


def make_pdf(text: str, pages: int = 1) -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text((72, 72), f"{text}\nPage {i + 1}")
    return doc.tobytes()


def make_png(color=(200, 120, 40), size=(300, 200)) -> bytes:
    img = Image.new("RGB", size, color)
    for x in range(0, size[0], 20):
        for y in range(size[1]):
            img.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()
