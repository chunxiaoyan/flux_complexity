"""Regression check against the legacy ud_calculation code and its saved Excel results.

Not part of the test suite: it needs the legacy source (extracted from
ud_calculation.rar) and the user's corpora, which are not in this repository.

Two comparisons per corpus file:
  A. new code WITHOUT parataxis cut  vs  legacy tree2flux + Flux.flux_weight run live
     (legacy = unpunctATree, no parataxis step). Expected: identical except sentences
     the legacy code skipped (punctuation with dependents).
  B. new code, parataxis mode "all"  vs  saved experimental_data_*.xlsx
     (produced by the lost update_parataxis_gov). Rows are aligned in order, since the
     Excel files carry no sentence id. Differences come from parataxis:* subtypes.
  C. new code, default parataxis mode "exact" (bare label only)  vs  saved Excel.
     Expected: identical — this is how the legacy function behaved.

Usage:
  python scripts/compare_legacy.py --legacy-src DIR_WITH_lib --corpus-root DIR
"""

from __future__ import annotations

import argparse
import collections
import collections.abc
import difflib
import sys
from pathlib import Path

from flux_complexity.cli import build_pipeline
from flux_complexity.core import compute_flux, process, read_conllu

PAIRS = {  # excel name -> conllu path relative to corpus root
    "C": "corpus_01032025/C.conllu",
    "I": "corpus_01032025/I.conllu",
    "PC": "corpus_01032025/PC.conllu",
    "PI": "corpus_01032025/PI.conllu",
    "CA": "corpus_02042025/CA.conllu",
    "CD": "corpus_02042025/CD.conllu",
    "CE": "corpus_02042025/CE.conllu",
    "CN": "corpus_02042025/CN.conllu",
}


def new_rows(path: Path, parataxis: str) -> list[tuple[int, int, str, str, int, int]]:
    pipeline = build_pipeline(parataxis)
    rows = []
    for k, sent in enumerate(read_conllu(path, "UD"), start=1):
        ps = process(sent, pipeline)
        for p in compute_flux(ps):
            rows.append((k, p.position, ps.word(p.position).form, ps.word(p.position + 1).form, p.size, p.weight))
    return rows


def legacy_rows(path: Path, conll, tree2flux, Flux):
    rows, skipped = [], 0
    for k, tree in enumerate(conll.conllFile2trees(str(path)), start=1):
        tree.addkids()
        t = tree.unpunctATree()
        if t is None:
            skipped += 1
            continue
        for i, item in sorted(tree2flux(t).items()):
            f = Flux(i, item)
            f.flux2matrice()
            size = len(f.matrice)
            f.flux_weight(f.matrice, 0)
            rows.append((k, i, t[i]["t"], t[i + 1]["t"], size, f.weight))
    return rows, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--legacy-src", type=Path, required=True, help="directory containing legacy lib/")
    ap.add_argument("--corpus-root", type=Path, required=True, help="the ud_calculation directory")
    ap.add_argument("--show-diff", action="store_true", help="print the differing rows of comparison B")
    args = ap.parse_args()

    collections.Mapping = collections.abc.Mapping  # legacy conll3 predates Python 3.10
    sys.path.insert(0, str(args.legacy_src))
    from lib import conll3 as conll  # type: ignore
    from lib.flux import Flux, tree2flux  # type: ignore

    import pandas as pd

    print(f"{'corpus':<6} | A: new(keep parataxis) vs legacy live | B: new(all) vs saved Excel | C")
    for name, rel in PAIRS.items():
        path = args.corpus_root / rel
        new_keep = new_rows(path, "keep")
        old, skipped = legacy_rows(path, conll, tree2flux, Flux)
        skipped_ids = {k for k, *_ in new_keep} - {k for k, *_ in old}
        new_comparable = [r for r in new_keep if r[0] not in skipped_ids]
        a_diff = sum(1 for x, y in zip(new_comparable, old) if x != y) + abs(len(new_comparable) - len(old))

        xl = pd.read_excel(args.corpus_root / f"experimental_data_{name}.xlsx")
        saved = [(int(r.flux_position), str(r.word1), str(r.word2), int(r.weight)) for r in xl.itertuples()]
        exact = [(pos, w1, w2, w) for _, pos, w1, w2, _, w in new_rows(path, "exact")]
        exact_ok = "identical" if exact == saved else "DIFFERENT"
        new_cut = [(pos, w1, w2, w) for _, pos, w1, w2, _, w in new_rows(path, "all")]
        sm = difflib.SequenceMatcher(a=new_cut, b=saved, autojunk=False)
        b_ops = collections.Counter()
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "equal":
                b_ops[op] += max(i2 - i1, j2 - j1)
        print(
            f"{name:<6} | rows {len(new_comparable):>5} vs {len(old):>5}, differing {a_diff:>3}, "
            f"legacy skipped {skipped} sent | new {len(new_cut):>5} vs saved {len(saved):>5}, "
            f"identical {sum(b.size for b in sm.get_matching_blocks()):>5}, other {dict(b_ops)}"
            f" | C: --parataxis exact vs saved: {exact_ok}"
        )
        if args.show_diff:
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op != "equal":
                    print(f"    {op}: new {new_cut[i1:i2]}  saved {saved[j1:j2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
