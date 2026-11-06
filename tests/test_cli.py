import csv
import pytest

from flux_complexity.cli import main

from .conftest import make_conllu

EX1 = [
    (1, "Le", "DET", 2, "det"),
    (2, "chat", "NOUN", 6, "nsubj"),
    (3, "de", "ADP", 5, "case"),
    (4, "ma", "DET", 5, "det"),
    (5, "sœur", "NOUN", 2, "nmod"),
    (6, "dort", "VERB", 0, "root"),
    (7, ".", "PUNCT", 6, "punct"),
]


def test_compute_writes_positions_and_sentences(tmp_path, capsys):
    f = tmp_path / "ex.conllu"
    f.write_text(make_conllu(EX1, "ex1"), encoding="utf-8")
    pos, sen = tmp_path / "p.csv", tmp_path / "s.csv"
    assert main(["compute", str(f), "--scheme", "UD", "-o", str(pos), "--sentences", str(sen)]) == 0

    rows = list(csv.DictReader(open(pos, encoding="utf-8-sig")))
    assert [(r["sent_id"], r["position"], r["size"], r["weight"]) for r in rows] == [
        ("ex1", "1", "1", "1"), ("ex1", "2", "2", "1"), ("ex1", "3", "3", "2"),
        ("ex1", "4", "4", "2"), ("ex1", "5", "1", "1"),
    ]  # fmt: skip
    assert (rows[3]["left_form"], rows[3]["right_form"]) == ("ma", "sœur")
    assert rows[0]["deps"] == "chat->Le:det"

    (s,) = list(csv.DictReader(open(sen, encoding="utf-8-sig")))
    assert (s["max_size"], s["mean_size"], s["max_weight"], s["mean_weight"]) == ("4", "2.2", "2", "1.4")
    assert "P(>=2)=0.4000" in capsys.readouterr().out


def test_parataxis_modes(tmp_path):
    rows = [(1, "a", "VERB", 0, "root"), (2, "b", "VERB", 1, "parataxis:insert")]
    f = tmp_path / "p.conllu"
    f.write_text(make_conllu(rows), encoding="utf-8")
    counts = {}
    for mode in ("all", "exact", "keep"):
        out = tmp_path / f"{mode}.csv"
        main(["compute", str(f), "--scheme", "UD", "-o", str(out), "--parataxis", mode])
        counts[mode] = len(list(csv.DictReader(open(out, encoding="utf-8-sig"))))
    assert counts == {"all": 0, "exact": 1, "keep": 1}
    default = tmp_path / "default.csv"
    main(["compute", str(f), "--scheme", "UD", "-o", str(default)])
    assert len(list(csv.DictReader(open(default, encoding="utf-8-sig")))) == counts["exact"]


def test_serve_opens_the_page_unless_told_not_to(monkeypatch, tmp_path):
    pytest.importorskip("uvicorn")
    import threading
    import uvicorn
    import webbrowser

    from flux_complexity import cli

    opened, timers = [], []

    class ImmediateTimer:
        def __init__(self, delay, fn, args=()):
            timers.append(delay)
            self.fn, self.args = fn, args

        def start(self):
            self.fn(*self.args)

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: opened.append(("run", kw["host"], kw["port"])))
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(("open", url)))
    monkeypatch.setattr(threading, "Timer", ImmediateTimer)
    db = str(tmp_path / "t.sqlite3")
    assert cli.main(["serve", "--no-parser", "--port", "8123", "--db", db]) == 0
    assert ("open", "http://127.0.0.1:8123/") in opened and ("run", "127.0.0.1", 8123) in opened
    opened.clear()
    assert cli.main(["serve", "--no-parser", "--no-browser", "--db", db]) == 0
    assert [o[0] for o in opened] == ["run"]
