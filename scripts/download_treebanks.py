"""Download the reference treebanks (spec §7) at a pinned release into data/raw/.

Uses shallow git clones of the official repositories:
  UD : https://github.com/UniversalDependencies/UD_French-<name>
  SUD: https://github.com/surfacesyntacticud/SUD_French-<name>

Usage: python scripts/download_treebanks.py [--release r2.18] [--dest data/raw]
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

TREEBANKS = ["Sequoia", "ParisStories", "Rhapsodie"]
ORGS = {"UD": "UniversalDependencies", "SUD": "surfacesyntacticud"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default="r2.18")
    ap.add_argument("--dest", type=Path, default=Path("data/raw"))
    args = ap.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)
    for scheme, org in ORGS.items():
        for tb in TREEBANKS:
            repo = f"{scheme}_French-{tb}"
            target = args.dest / f"{repo}@{args.release}"
            if target.exists():
                print(f"skip {target} (exists)")
                continue
            url = f"https://github.com/{org}/{repo}.git"
            print(f"clone {url} @ {args.release}")
            subprocess.run(
                ["git", "clone", "-q", "--depth", "1", "--branch", args.release, url, str(target)],
                check=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
