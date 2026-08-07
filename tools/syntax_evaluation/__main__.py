"""Command-line interface for deterministic syntax-prototype evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .evaluation import evaluate_corpus
from .limits import PrototypeError


ROOT = Path(__file__).parents[2].resolve()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Evaluate Atrinik authored-syntax prototypes")
    root.add_argument("--root", type=Path, default=ROOT)
    root.add_argument("--json", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    options = parser().parse_args(argv)
    try:
        report = evaluate_corpus(options.root)
    except (OSError, PrototypeError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 1
    if options.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            "authored syntax prototypes: valid "
            "({} fixtures, {} formats, {} byte-exact and {} semantic round-trips)".format(
                summary["fixtures"],
                len(summary["formats"]),
                summary["byte_exact_roundtrips"],
                summary["semantic_roundtrips"],
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
