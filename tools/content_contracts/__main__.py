"""Command-line validation and inspection for content contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts import ContractError, confined_file, load_json, validate_contracts
from .corpus import inspect_document, validate_corpus


ROOT = Path(__file__).parents[2].resolve()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Validate Atrinik content contracts")
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--root", type=Path, default=ROOT)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--root", type=Path, default=ROOT)
    inspect.add_argument("--format", choices=("archetype", "map"), required=True)
    inspect.add_argument("path", type=Path)
    return root


def main(argv: list[str] | None = None) -> int:
    options = parser().parse_args(argv)
    try:
        root = options.root.resolve(strict=True)
        schemas = validate_contracts(root)
        if options.command == "validate":
            report = validate_corpus(root, schemas)
            print(
                "content contracts: valid "
                "({} consumers, {} fixtures, {} features, {} load modes)".format(
                    report["consumer_count"],
                    len(report["fixtures"]),
                    report["feature_count"],
                    report["load_mode_count"],
                )
            )
            return 0
        validate_corpus(root, schemas)
        grammar = load_json(root / "contracts" / "content-v1" / "grammar-inventory.json")
        candidate = options.path if options.path.is_absolute() else root / options.path
        relative = candidate.relative_to(root)
        resolved = confined_file(root, relative.as_posix(), "inspection input")
        inspection, _ = inspect_document(
            resolved,
            options.format,
            grammar,
            display_path=resolved.relative_to(root).as_posix(),
        )
        print(json.dumps(inspection, indent=2, sort_keys=True))
        return 0
    except (ContractError, OSError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
