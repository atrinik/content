"""Versioned headless CLI for safe authored-content inspection and edits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence

from tools.content_contracts.contracts import (
    ContractError,
    confined_file,
    load_json,
    validate_contract_document,
    validate_contracts,
)

from .contracts import (
    validate_core_contracts,
    validate_core_document,
)
from .errors import ContentCoreError
from .operations import semantic_comparison
from .project import ProjectIndex
from .transaction import prepare_transaction, publish_transaction


EXIT_SUCCESS = 0
EXIT_DIFFERENT = 1
EXIT_SYNTAX = 3
EXIT_CONFLICT = 4
EXIT_SAFETY = 5
EXIT_IO = 6
EXIT_SCHEMA = 7


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atrinik-content",
        description="Inspect and safely edit Atrinik authored content.",
    )
    parser.add_argument("--version", action="version", version="atrinik-content 1")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)

    for command in ("inspect", "validate"):
        subparser = commands.add_parser(command)
        subparser.add_argument("path")
        subparser.add_argument("--format", choices=("archetype", "map"))
        subparser.add_argument("--json", action="store_true")

    diff = commands.add_parser("diff")
    diff.add_argument("left")
    diff.add_argument("right")
    diff.add_argument("--format", choices=("archetype", "map"))
    diff.add_argument("--semantic", action="store_true", required=True)
    diff.add_argument("--json", action="store_true")

    catalog = commands.add_parser("catalog")
    catalog_commands = catalog.add_subparsers(dest="catalog_command", required=True)
    search = catalog_commands.add_parser("search")
    search.add_argument("--kind")
    search.add_argument("--text", required=True)
    search.add_argument("--limit", type=int, default=50)
    search.add_argument("--json", action="store_true")

    apply = commands.add_parser("apply")
    apply.add_argument("--patch", required=True)
    apply.add_argument(
        "--apply",
        action="store_true",
        help="publish after full validation; without this flag the command is a dry run",
    )
    apply.add_argument("--diff", action="store_true")
    apply.add_argument("--json", action="store_true")
    return parser


def _json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ) + "\n"


def _emit(value: Mapping[str, Any], *, json_mode: bool, human: str) -> None:
    if json_mode:
        sys.stdout.write(_json(value))
    else:
        print(human)


def _format_error(error: BaseException) -> tuple[Mapping[str, Any], int]:
    if isinstance(error, ContentCoreError):
        exits = {
            "conflict": EXIT_CONFLICT,
            "encoding": EXIT_SYNTAX,
            "io": EXIT_IO,
            "safety": EXIT_SAFETY,
            "schema": EXIT_SCHEMA,
            "syntax": EXIT_SYNTAX,
        }
        return error.to_dict(), exits.get(error.kind, EXIT_SCHEMA)
    if isinstance(error, ContractError):
        wrapped = ContentCoreError(
            str(error), kind="schema", code="invalid-json-contract"
        )
        return wrapped.to_dict(), EXIT_SCHEMA
    if isinstance(error, OSError):
        wrapped = ContentCoreError(
            str(error), kind="io", code="content-io-error", retryable=True
        )
        return wrapped.to_dict(), EXIT_IO
    wrapped = ContentCoreError(str(error), code="unexpected-content-error")
    return wrapped.to_dict(), EXIT_SCHEMA


def main(argv: Optional[Sequence[str]] = None) -> int:
    options = _parser().parse_args(argv)
    json_mode = bool(getattr(options, "json", False))
    try:
        root = options.root.resolve(strict=True)
        core_schemas = validate_core_contracts(root)
        project = ProjectIndex(root, schema_root=root)
        if options.command in ("inspect", "validate"):
            document = project.document(options.path, format_name=options.format)
            inspection = document.inspection()
            validate_core_document("inspection", inspection, core_schemas)
            _emit(
                inspection,
                json_mode=json_mode,
                human="{}: {} nodes, {} diagnostics, {}".format(
                    document.path,
                    len(document.nodes),
                    len(document.diagnostics),
                    "valid" if document.valid else "invalid",
                ),
            )
            return EXIT_SUCCESS if document.valid else EXIT_SYNTAX

        if options.command == "diff":
            contract_schemas = validate_contracts(root)
            left = project.document(options.left, format_name=options.format)
            right = project.document(options.right, format_name=options.format)
            comparison = semantic_comparison(left, right)
            validate_contract_document(
                "semantic-comparison", comparison, contract_schemas
            )
            _emit(
                comparison,
                json_mode=json_mode,
                human=(
                    "equivalent"
                    if comparison["equivalent"]
                    else _json(comparison)
                ),
            )
            return EXIT_SUCCESS if comparison["equivalent"] else EXIT_DIFFERENT

        if options.command == "catalog":
            result = project.search(
                kind=options.kind,
                text=options.text,
                limit=options.limit,
            )
            validate_core_document("catalog-search", result, core_schemas)
            _emit(
                result,
                json_mode=json_mode,
                human="\n".join(
                    "{}:{}\t{}".format(
                        item["domain"], item["key"], item["location"]["path"]
                    )
                    for item in result["results"]
                ),
            )
            return EXIT_SUCCESS

        patch_path = confined_file(root, options.patch, "transaction input")
        transaction = load_json(patch_path)
        validate_core_document("transaction", transaction, core_schemas)
        prepared = prepare_transaction(root, transaction, schema_root=root)
        result = prepared.result(dry_run=not options.apply, applied=options.apply)
        validate_core_document("transaction-result", result, core_schemas)
        if options.apply:
            publish_transaction(root, prepared)
        if json_mode:
            sys.stdout.write(_json(result))
        else:
            if options.diff or not options.apply:
                for item in result["files"]:
                    sys.stdout.write(item["diff"])
            print(
                "{} {} file(s)".format(
                    "applied" if options.apply else "dry-run validated",
                    len(result["files"]),
                )
            )
        return EXIT_SUCCESS
    except (ContentCoreError, ContractError, OSError, ValueError) as error:
        payload, exit_code = _format_error(error)
        if json_mode:
            sys.stdout.write(_json(payload))
        else:
            print("error: {}".format(payload["message"]), file=sys.stderr)
        return exit_code
