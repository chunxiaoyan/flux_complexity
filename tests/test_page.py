"""The beginner page is served, self-contained (offline) and in sync with Python defaults.

Behaviour in a real browser (colours, hover arcs, upload) was checked manually;
see docs/review_stage5.md.
"""

import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from flux_complexity.norms import DEFAULT_THRESHOLDS  # noqa: E402
from flux_complexity.web.app import STATIC_DIR, create_app  # noqa: E402


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "t.sqlite3", load_parser=False)) as c:
        yield c


def test_page_and_assets_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert '<html lang="fr">' in r.text and "Analyser" in r.text
    assert r.headers["cache-control"] == "no-cache"  # never stale after an upgrade
    for asset in ("/static/app.js", "/static/style.css"):
        a = client.get(asset)
        assert a.status_code == 200 and a.headers["cache-control"] == "no-cache"
    assert "/" not in client.get("/openapi.json").json()["paths"]  # page not listed as an API


def test_page_has_no_external_resources():
    for f in STATIC_DIR.iterdir():
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"(src|href)=[\"']https?://", text), f.name
        assert "fetch(\"http" not in text and "fetch('http" not in text, f.name


def test_page_never_injects_html():
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js and "insertAdjacentHTML" not in js


def test_js_default_thresholds_match_python():
    js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    m = re.search(r"DEFAULT_THRESHOLDS = \{ weight: \[([^\]]+)\], size: \[([^\]]+)\] \}", js)
    as_frac = lambda s: tuple(round(float(x) / 100, 6) for x in s.split(","))  # noqa: E731
    assert as_frac(m.group(1)) == DEFAULT_THRESHOLDS["weight"]
    assert as_frac(m.group(2)) == DEFAULT_THRESHOLDS["size"]
    for metric in ("weight", "size"):
        row = re.search(rf'<tr data-metric="{metric}">(.*?)</tr>', html, re.S).group(1)
        values = tuple(round(float(v) / 100, 6) for v in re.findall(r'value="([\d.]+)"', row))
        assert values == DEFAULT_THRESHOLDS[metric]
