"""Command line: `fluxcalc compute FILE.conllu --scheme UD -o positions.csv`.

Outputs (UTF-8 with BOM so Excel shows accents correctly):
- positions CSV: one row per non-empty flux position, with sent_id;
- optional sentences CSV: one row per sentence (max/mean size and weight);
- optional warnings file; a corpus summary is printed at the end.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .core import (
    PARATAXIS_MODES,
    CorpusSummary,
    build_pipeline,
    compute_flux,
    process,
    read_conllu,
    summarize_sentence,
)

POSITION_COLUMNS = [
    "sent_id", "position", "left_id", "left_form", "right_id", "right_form",
    "size", "weight", "deps",
]  # fmt: skip
SENTENCE_COLUMNS = [
    "sent_id", "n_words", "n_positions", "max_size", "mean_size", "max_weight", "mean_weight", "text",
]  # fmt: skip


def _fmt(x: float | None) -> str:
    return "" if x is None else f"{x:.4f}".rstrip("0").rstrip(".")


def compute_file(
    path: Path,
    scheme: str,
    positions_out: Path,
    sentences_out: Path | None = None,
    warnings_out: Path | None = None,
    parataxis: str = "exact",
) -> CorpusSummary:
    pipeline = build_pipeline(parataxis)
    summary = CorpusSummary()
    pos_fh = open(positions_out, "w", newline="", encoding="utf-8-sig")
    sent_fh = open(sentences_out, "w", newline="", encoding="utf-8-sig") if sentences_out else None
    warn_fh = open(warnings_out, "w", encoding="utf-8") if warnings_out else None
    try:
        pos_w = csv.writer(pos_fh)
        pos_w.writerow(POSITION_COLUMNS)
        sent_w = csv.writer(sent_fh) if sent_fh else None
        if sent_w:
            sent_w.writerow(SENTENCE_COLUMNS)
        for sent in read_conllu(path, scheme):
            ps = process(sent, pipeline)
            positions = compute_flux(ps)
            summary.add(positions, len(ps.warnings))
            for p in positions:
                left, right = ps.word(p.position), ps.word(p.position + 1)
                deps = "|".join(
                    f"{ps.word(d.gov).form}->{ps.word(d.dep).form}:{d.deprel}" for d in p.deps
                )
                pos_w.writerow([
                    sent.sent_id, p.position, left.id, left.form, right.id, right.form,
                    p.size, p.weight, deps,
                ])  # fmt: skip
            if sent_w:
                s = summarize_sentence(sent.sent_id, ps.n, positions)
                sent_w.writerow([
                    s.sent_id, s.n_words, s.n_positions, s.max_size or "", _fmt(s.mean_size),
                    s.max_weight or "", _fmt(s.mean_weight), sent.text or "",
                ])  # fmt: skip
            if warn_fh:
                for w in ps.warnings:
                    warn_fh.write(w + "\n")
    finally:
        pos_fh.close()
        if sent_fh:
            sent_fh.close()
        if warn_fh:
            warn_fh.close()
    return summary


def format_summary(summary: CorpusSummary, pipeline: str) -> str:
    lines = [
        f"pipeline           : {pipeline}",
        f"sentences          : {summary.n_sentences}"
        f" ({summary.n_sentences_without_flux} without any flux)",
        f"flux positions     : {summary.size.total}",
        f"warnings           : {summary.n_warnings}",
    ]
    for name, dist in (("size", summary.size), ("weight", summary.weight)):
        if not dist.total:
            continue
        lines.append(f"{name:<7} mean={dist.mean:.3f} std={dist.std:.3f} max={max(dist.counts)}")
        for k in sorted(dist.counts):
            lines.append(f"    {name}={k:<3} n={dist.counts[k]:<7} P(>={k})={dist.tail(k):.4f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fluxcalc", description="Dependency flux size and weight.")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compute", help="compute flux size/weight for a .conllu file")
    c.add_argument("file", type=Path)
    c.add_argument("--scheme", choices=["UD", "SUD"], required=True)
    c.add_argument("-o", "--output", type=Path, help="positions CSV (default: <file>.positions.csv)")
    c.add_argument("--sentences", type=Path, help="also write a per-sentence CSV")
    c.add_argument("--warnings", type=Path, help="write preprocessing warnings to this file")
    c.add_argument(
        "--parataxis",
        choices=list(PARATAXIS_MODES),
        default="exact",
        help="; ".join(f"{k}: {v}" for k, v in PARATAXIS_MODES.items()),
    )
    n = sub.add_parser("norms", help="list or inspect reference norms")
    nsub = n.add_subparsers(dest="norms_command", required=True)
    nsub.add_parser("list", help="list built-in norms")
    show = nsub.add_parser("show", help="show a norm with its colour levels")
    show.add_argument("norm", help="built-in norm name or path to a norm JSON file")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if args.command == "norms":
        return _norms_command(args)

    out = args.output or args.file.with_suffix(".positions.csv")
    summary = compute_file(args.file, args.scheme, out, args.sentences, args.warnings, args.parataxis)
    pipeline = " -> ".join(t.name for t in build_pipeline(args.parataxis))
    print(format_summary(summary, pipeline))
    print(f"positions written to {out}")
    return 0


def _norms_command(args: argparse.Namespace) -> int:
    from .norms import DEFAULT_THRESHOLDS, Norm, list_builtin

    if args.norms_command == "list":
        for name in list_builtin():
            d = Norm.builtin(name).data
            print(f"{name:<26} {d['scheme']:<4} {d['release']:<6} "
                  f"sentences={d['n_sentences']:>6} positions={d['n_positions']:>7}")  # fmt: skip
        return 0
    norm = Norm.load(args.norm) if args.norm.endswith(".json") else Norm.builtin(args.norm)
    d = norm.data
    print(f"{d['name']}  scheme={d['scheme']}  release={d['release']}  pipeline={' -> '.join(d['pipeline'])}")
    print(f"sentences={d['n_sentences']}  positions={d['n_positions']}  warnings={d['n_warnings']}")
    th = " / ".join(f"{t:.0%}" for t in DEFAULT_THRESHOLDS)
    for metric in ("weight", "size"):
        m = d["metrics"][metric]
        print(f"\n{metric}: mean={m['mean']} std={m['std']} max={m['max']}   (levels: P <= {th})")
        for k, c in m["counts"].items():
            v = int(k)
            print(f"  {metric}={v:<3} n={c:<8} P(>={v})={norm.tail(metric, v):.4f}  level={norm.level(metric, v)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
