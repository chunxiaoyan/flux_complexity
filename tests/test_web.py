"""API and database tests with a fake parser (no Stanza needed)."""

import csv
import io
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

LOCAL = "http://127.0.0.1:8000"

from flux_complexity.core import parse_conllu  # noqa: E402
from flux_complexity.parse import ParserInfo  # noqa: E402
from flux_complexity.web.app import create_app  # noqa: E402

from .conftest import make_conllu  # noqa: E402

EX1 = [
    (1, "Le", "DET", 2, "det"), (2, "chat", "NOUN", 6, "nsubj"), (3, "de", "ADP", 5, "case"),
    (4, "ma", "DET", 5, "det"), (5, "sœur", "NOUN", 2, "nmod"), (6, "dort", "VERB", 0, "root"),
    (7, ".", "PUNCT", 6, "punct"),
]  # fmt: skip
PARA = [
    (1, "Il", "PRON", 2, "nsubj"), (2, "pleut", "VERB", 0, "root"), (3, ",", "PUNCT", 5, "punct"),
    (4, "je", "PRON", 5, "nsubj"), (5, "reste", "VERB", 2, "parataxis:insert"), (6, ".", "PUNCT", 2, "punct"),
]  # fmt: skip
CORPUS = make_conllu(EX1, "a") + make_conllu(PARA, "b")


class FakeParser:
    def parse(self, text):
        return parse_conllu(make_conllu(EX1, "s1"), "UD")

    def info(self):
        return ParserInfo("fr", "fake", {"depparse": "fake.pt"})


class BrokenParser(FakeParser):
    def parse(self, text):
        raise RuntimeError("no model")


def wait_ready(client, timeout=5):
    t0 = time.time()
    while client.get("/api/health").json()["parser"] == "loading" and time.time() - t0 < timeout:
        time.sleep(0.01)
    return client.get("/api/health").json()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "t.sqlite3", parser=FakeParser()), base_url=LOCAL) as c:
        assert wait_ready(c)["parser"] == "ready"
        yield c


def upload(client, text=CORPUS, **form):
    files = {"file": ("mini.conllu", text.encode("utf-8"), "text/plain")}
    return client.post("/api/corpora", files=files, data={"scheme": "UD", **form})


def test_health_and_norms(client):
    h = client.get("/api/health").json()
    assert h["parser_info"]["stanza"] == "fake"
    norms = client.get("/api/norms").json()
    assert len(norms) == 8
    assert [n["name"] for n in norms if n["default"]] == ["SUD_French-Sequoia", "UD_French-Sequoia"]
    assert client.get("/api/norms/UD_French-Rhapsodie").json()["release"] == "r2.18"
    assert client.get("/api/norms/nope").status_code == 404


def test_analyze_text(client):
    r = client.post("/api/analyze/text", json={"text": "Le chat de ma sœur dort."})
    assert r.status_code == 200
    d = r.json()
    assert d["norm"] == "UD_French-Sequoia" and d["parser"]["stanza"] == "fake"
    assert [(p["size"], p["weight"]) for p in d["sentences"][0]["positions"]] == [
        (1, 1), (2, 1), (3, 2), (4, 2), (1, 1)
    ]  # fmt: skip


def test_analyze_text_errors_are_french(client):
    assert client.post("/api/analyze/text", json={"text": "  "}).json()["detail"] == "Le texte est vide."
    r = client.post("/api/analyze/text", json={"text": "x", "norm": "SUD_French-Sequoia"})
    assert r.status_code == 422 and "UD" in r.json()["detail"]
    r = client.post("/api/analyze/text", json={"text": "x", "thresholds": {"weight": [2]}})
    assert r.status_code == 422 and "Seuils invalides" in r.json()["detail"]
    assert client.post("/api/analyze/text", json={"text": "x" * 20_001}).status_code == 422


def test_parser_unavailable(tmp_path):
    with TestClient(create_app(tmp_path / "t.sqlite3", parser=BrokenParser()), base_url=LOCAL) as c:
        h = wait_ready(c)
        assert h["parser"] == "unavailable" and "no model" in h["parser_error"]
        r = c.post("/api/analyze/text", json={"text": "Bonjour."})
        assert r.status_code == 503 and "n'est pas disponible" in r.json()["detail"]


def test_no_parser_mode_still_serves_conllu(tmp_path):
    with TestClient(create_app(tmp_path / "t.sqlite3", load_parser=False), base_url=LOCAL) as c:
        assert c.get("/api/health").json()["parser"] == "disabled"
        files = {"file": ("x.conllu", CORPUS.encode(), "text/plain")}
        r = c.post("/api/analyze/conllu", files=files, data={"scheme": "SUD"})
        assert r.status_code == 200 and r.json()["norm"] == "SUD_French-Sequoia"


def test_analyze_conllu_upload_errors(client):
    files = {"file": ("x.conllu", "1\tA\n".encode(), "text/plain")}
    r = client.post("/api/analyze/conllu", files=files, data={"scheme": "UD"})
    assert r.status_code == 422 and r.json()["detail"].startswith("Fichier CoNLL-U invalide")
    files = {"file": ("x.conllu", CORPUS.encode(), "text/plain")}
    r = client.post("/api/analyze/conllu", files=files, data={"scheme": "UD", "norm": "SUD_French-Sequoia"})
    assert r.status_code == 422
    files = {"file": ("x.conllu", "é".encode("latin-1"), "text/plain")}
    assert "UTF-8" in client.post("/api/analyze/conllu", files=files, data={"scheme": "UD"}).json()["detail"]


def test_import_query_detail_export_delete(client):
    r = upload(client)
    assert r.status_code == 201
    c = r.json()
    assert (c["name"], c["n_sentences"], c["n_positions"], c["parataxis"]) == ("mini", 2, 8, "exact")
    # exact mode keeps parataxis:insert -> PARA has 3 positions (1 1 1); EX1 has weights 1,1,2,2,1
    assert c["weight_counts"] == {"1": 6, "2": 2} and c["size_counts"]["4"] == 1
    cid = c["id"]
    assert [x["id"] for x in client.get("/api/corpora").json()] == [cid]

    q = client.get(f"/api/corpora/{cid}/sentences", params={"min_weight": 2}).json()
    assert q["total"] == 1 and q["sentences"][0]["sent_id"] == "a"
    q = client.get(f"/api/corpora/{cid}/sentences", params={"deprel": "parataxis:insert"}).json()
    assert [s["sent_id"] for s in q["sentences"]] == ["b"]
    q = client.get(f"/api/corpora/{cid}/sentences", params={"min_weight": 2, "deprel": "det"}).json()
    assert q["total"] == 1  # det of "ma" is inside the weight-2 flux at ma|sœur
    q = client.get(f"/api/corpora/{cid}/sentences", params={"min_weight": 2, "deprel": "parataxis:insert"}).json()
    assert q["total"] == 0  # conditions must hold in the same position

    sid = client.get(f"/api/corpora/{cid}/sentences").json()["sentences"][0]["id"]
    s = client.get(f"/api/sentences/{sid}").json()
    assert s["sent_id"] == "a" and len(s["flux"]) == 5
    pos4 = s["flux"][3]
    assert (pos4["size"], pos4["weight"]) == (4, 2)
    # deps in (left, right) order: chat->sœur (2,5), dort->chat (2,6), sœur->de (3,5), sœur->ma (4,5)
    # rows = left ends ascending (2,3,4), cols = right ends descending (6,5)
    assert [(d["row"], d["col"]) for d in pos4["deps"]] == [(1, 2), (1, 1), (2, 2), (3, 2)]
    assert [p["weight"] for p in s["analysis"]["sentences"][0]["positions"]] == [f["weight"] for f in s["flux"]]

    r = client.get(f"/api/corpora/{cid}/export.csv")
    assert r.headers["content-disposition"] == 'attachment; filename="mini.positions.csv"'
    rows = list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"))))
    assert len(rows) == 8 and rows[3]["left_form"] == "ma" and rows[3]["deps"].startswith("chat->sœur:nmod")

    assert client.delete(f"/api/corpora/{cid}").status_code == 204
    assert client.get(f"/api/corpora/{cid}").status_code == 404
    assert client.get(f"/api/sentences/{sid}").status_code == 404  # cascade


def test_detail_uses_import_parataxis_mode(client):
    cid = upload(client, parataxis="all").json()["id"]
    sent_b = client.get(f"/api/corpora/{cid}/sentences").json()["sentences"][1]
    s = client.get(f"/api/sentences/{sent_b['id']}").json()
    stored = [f["position"] for f in s["flux"]]
    analysed = [p["position"] for p in s["analysis"]["sentences"][0]["positions"]]
    assert stored == analysed == [1, 3]  # parataxis:insert cut -> position 2 empty


def test_matches_cli_on_real_corpus(client, tmp_path):
    """The DB stores exactly what `fluxcalc compute` writes (spec-level consistency)."""
    from flux_complexity.cli import compute_file

    text = CORPUS * 3
    cid = upload(client, text=text).json()["id"]
    f = tmp_path / "c.conllu"
    f.write_text(text, encoding="utf-8")
    compute_file(f, "UD", tmp_path / "p.csv")
    cli_rows = list(csv.reader(open(tmp_path / "p.csv", encoding="utf-8-sig")))
    api_rows = list(csv.reader(io.StringIO(client.get(f"/api/corpora/{cid}/export.csv").content.decode("utf-8-sig"))))
    assert cli_rows == api_rows


def test_search_filters_and_matrix_shape(client):
    cid = upload(client).json()["id"]
    assert "nmod" in client.get(f"/api/corpora/{cid}").json()["deprels"]

    def search(**params):
        q = client.get(f"/api/corpora/{cid}/sentences", params=params)
        assert q.status_code == 200, q.text
        return [(s["sent_id"], s["positions"]) for s in q.json()["sentences"]]

    # every returned sentence lists the positions that satisfy the conditions
    assert search(min_weight=2) == [("a", [3, 4])]
    assert search(min_size=3, max_size=3) == [("a", [3])]
    assert search(max_weight=1) == [("a", [1, 2, 5]), ("b", [1, 2, 3])]
    assert search() == [("a", []), ("b", [])]  # no position condition
    # a relation without subtype also matches its subtypes; with a subtype, exactly
    assert search(deprel="parataxis") == [("b", [2, 3])]  # pleut->reste spans pleut|je and je|reste
    assert search(deprel="parataxis:insert") == [("b", [2, 3])]
    assert search(deprel="parataxis:obj") == []
    # text: case-insensitive, also for non-ASCII letters
    assert [s for s, _ in search(text="SŒUR")] == ["a"]

    # flux matrix of a at de|ma (position 3): rows chat, de; cols dort, sœur
    #   (1,1) dort->chat  (1,2) chat->sœur  (2,2) sœur->de
    assert search(matrix="1,1 1,2 2,2") == [("a", [3])]  # exact shape (legacy list_mat)
    assert search(matrix="1,1 2,2") == []  # no flux is exactly two disjoint deps here
    assert search(matrix="1,1 2,2", matrix_mode="contains") == [("a", [3, 4])]
    assert search(matrix="1,1") == [("a", [1, 5]), ("b", [1, 2])]  # = positions of size 1
    assert search(matrix="1,1 2,2", matrix_mode="contains", min_size=4) == [("a", [4])]

    r = client.get(f"/api/corpora/{cid}/sentences", params={"matrix": "1;x"})
    assert r.status_code == 422 and "Case de matrice invalide" in r.json()["detail"]


def test_only_local_pages_can_use_the_server(client):
    files = {"file": ("x.conllu", CORPUS.encode(), "text/plain")}
    # DNS rebinding: another site's name in Host, even for reads
    assert client.get("/api/corpora", headers={"Host": "evil.example:8000"}).status_code == 403
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    # cross-site form POST / DELETE from another page
    r = client.post("/api/corpora", files=files, data={"scheme": "UD"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and client.get("/api/corpora").json() == []
    assert client.post("/api/corpora", files=files, data={"scheme": "UD"}, headers={"Origin": "null"}).status_code == 403
    # the page itself, localhost and [::1], and clients without Origin (curl, scripts) are fine
    for host, origin in [("127.0.0.1:8000", "http://127.0.0.1:8000"), ("localhost:8080", "http://localhost:8080"),
                         ("[::1]:8000", "http://[::1]:8000"), ("127.0.0.1:8000", None)]:
        headers = {"Host": host} | ({"Origin": origin} if origin else {})
        r = client.post("/api/corpora", files=files, data={"scheme": "UD"}, headers=headers)
        assert r.status_code == 201, (host, origin)
        assert client.delete(f"/api/corpora/{r.json()['id']}", headers=headers).status_code == 204


def test_matrix_and_deprel_bounds(client):
    files = {"file": ("x.conllu", CORPUS.encode(), "text/plain")}
    cid = client.post("/api/corpora", files=files, data={"scheme": "UD"}).json()["id"]
    assert client.get(f"/api/corpora/{cid}/sentences", params={"matrix": "1,99999999999999999999"}).status_code == 422
    assert client.get(f"/api/corpora/{cid}/sentences", params={"deprel": "x" * 41}).status_code == 422
