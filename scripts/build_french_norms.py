"""Build the 8 built-in French norms (spec §7) from data/raw/ (see download_treebanks.py).

For each scheme (UD, SUD): one norm per treebank + one merged norm of the three
(positions pooled, so larger treebanks weigh more). Only top-level *.conllu files
of each repository are used (SUD_French-Rhapsodie also ships prosody variants in
sub-folders, which are skipped).

Usage: python scripts/build_french_norms.py [--raw data/raw] [--release r2.18]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from flux_complexity.core import build_pipeline
from flux_complexity.norms import build_norm, write_norm

TREEBANKS = ["Sequoia", "ParisStories", "Rhapsodie"]
OUT = Path(__file__).resolve().parents[1] / "src" / "flux_complexity" / "norms" / "data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=Path("data/raw"))
    ap.add_argument("--release", default="r2.18")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    pipeline = build_pipeline("exact")
    for scheme in ("UD", "SUD"):
        all_files, names = [], []
        for tb in TREEBANKS:
            name = f"{scheme}_French-{tb}"
            files = sorted((args.raw / f"{name}@{args.release}").glob("*.conllu"))
            if not files:
                raise SystemExit(f"no .conllu files for {name}; run scripts/download_treebanks.py first")
            norm = build_norm(files, scheme, name, [name], args.release, pipeline)
            write_norm(norm, args.out / f"{name}.json")
            print(f"{name:<26} sentences={norm['n_sentences']:>6} positions={norm['n_positions']:>7} "
                  f"warnings={norm['n_warnings']:>4} "
                  f"P(w>=2)={norm['metrics']['weight']['tail'].get('2', 0):.4f} "
                  f"P(w>=3)={norm['metrics']['weight']['tail'].get('3', 0):.4f}")  # fmt: skip
            all_files += files
            names.append(name)
        merged = f"{scheme}_French-merged"
        norm = build_norm(all_files, scheme, merged, names, args.release, pipeline)
        write_norm(norm, args.out / f"{merged}.json")
        print(f"{merged:<26} sentences={norm['n_sentences']:>6} positions={norm['n_positions']:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
