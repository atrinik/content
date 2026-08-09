"""Command-line interface for authoritative schema generation and validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Optional, Sequence

from .audit import audit_corpus
from .generate import check_outputs, write_outputs
from .model import SchemaError, field_definitions, load_schema_source


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate and validate Atrinik authored-content schema metadata."
    )
    parser.add_argument(
        "command",
        choices=("audit", "check", "generate", "validate"),
        nargs="?",
        default="validate",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true", help="emit the audit report as JSON")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        source = load_schema_source(root)
        fields = field_definitions(source)
        if args.command == "generate":
            write_outputs(root)
            print("Generated {} authored-content schema projections.".format(5))
            return 0
        if args.command in ("check", "validate"):
            check_outputs(root)
        report = None
        if args.command in ("audit", "validate"):
            report = audit_corpus(root)
        if args.json and report is not None:
            print(json.dumps(report, indent=2, sort_keys=True))
        elif report is not None:
            print(
                "Content schema: {} fields, {} archetype files, {} maps, "
                "{} artifact files, {} properties, {} unexplained fields".format(
                    len(fields),
                    report["files"]["archetype"],
                    report["files"]["map"],
                    report["files"]["artifact"],
                    report["properties"],
                    len(report["unexplained_fields"]),
                )
            )
        else:
            print("Content schema: {} generated fields are current.".format(len(fields)))
        return 0
    except (OSError, SchemaError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
