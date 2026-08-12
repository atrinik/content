#!/usr/bin/env python3
"""Validate Atrinik's deterministic cross-release-line parity ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.content_contracts.contracts import (  # noqa: E402
    ContractError,
    load_json,
    validate_instance,
    validate_schema,
)


LEDGER_PATH = Path("contracts/release-lines/parity-ledger.json")
SCHEMA_PATH = Path("contracts/release-lines/parity-ledger.schema.json")
SCHEMA_NAME = "release-line-parity-ledger"
FORBIDDEN_PREFIXES = (
    "maps/light-source-evidence/",
    "build/",
)
FORBIDDEN_PATHS = {
    "maps/light-source-evidence-manifest.json",
    "tools/light-source-review/dark-lab",
    "tools/light_review_evidence.py",
    "tools/tests/test_light_review_evidence.py",
}
LINE_IDENTITIES = {"2.0": "main", "1.x": "1.x"}


class ParityError(ValueError):
    """The release-line ledger or its audited history is inconsistent."""


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or str(error)
        raise ParityError("git history query failed: {}".format(detail)) from error
    return result.stdout


def _line_identity(root: Path) -> str:
    try:
        value = (root / "release-line.txt").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        raise ParityError("cannot read release-line identity: {}".format(error)) from error
    try:
        return LINE_IDENTITIES[value]
    except KeyError as error:
        raise ParityError("unknown release-line identity: {!r}".format(value)) from error


def _safe_path(value: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts or "." in path.parts:
        raise ParityError("unsafe ledger path: {}".format(value))
    if value in FORBIDDEN_PATHS or any(value.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        raise ParityError("retired evidence or generated path is forbidden: {}".format(value))


def _strictly_sorted_unique(values: list[Any], context: str) -> None:
    if values != sorted(values) or len(values) != len(set(values)):
        raise ParityError("{} must be sorted and unique".format(context))


def validate_document(
    document: Mapping[str, Any],
    *,
    root: Path | None = None,
    check_history: bool = True,
) -> dict[str, Any]:
    """Apply relational invariants that JSON Schema cannot express."""

    horizons = document["horizons"]
    terminal = document["terminal_plan"]
    if set(horizons) != {"main", "1.x"}:
        raise ParityError("horizons must name exactly main and 1.x")

    terminal_prs: set[int] = set()
    for line in ("main", "1.x"):
        plan = terminal[line]
        if plan["horizon"] != horizons[line]:
            raise ParityError("{} terminal horizon contradicts horizons".format(line))
        commits = plan["commits"]
        if [entry["ordinal"] for entry in commits] != list(range(1, len(commits) + 1)):
            raise ParityError("{} terminal ordinals must be contiguous".format(line))
        if [entry["issue"] for entry in commits] != [137, 139]:
            raise ParityError("{} terminal order must be #137 then #139".format(line))
        for entry in commits:
            paths = entry["paths"]
            _strictly_sorted_unique(paths, "{} ordinal {} paths".format(line, entry["ordinal"]))
            for path in paths:
                _safe_path(path)
            pull_request = entry["pull_request"]
            if terminal["state"] == "declared":
                if not isinstance(pull_request, int) or isinstance(pull_request, bool):
                    raise ParityError("declared terminal entries require pull requests")
                if pull_request in terminal_prs:
                    raise ParityError("terminal pull requests must be unique")
                terminal_prs.add(pull_request)
            elif pull_request is not None:
                raise ParityError("prepublication terminal entries must not name pull requests")

    outcomes = document["outcomes"]
    outcome_ids = [outcome["id"] for outcome in outcomes]
    expected_ids = ["outcome-{:03d}".format(index) for index in range(1, len(outcomes) + 1)]
    if outcome_ids != expected_ids:
        raise ParityError("outcome IDs must be contiguous and deterministic")

    endpoints: dict[tuple[str, str], tuple[str, int]] = {}
    pending = []
    for outcome in outcomes:
        classification = outcome["classification"]
        destination = outcome["destination"]
        if classification == "exempt" and destination:
            raise ParityError("{} exempt outcome has a destination".format(outcome["id"]))
        if classification in {"exact", "equivalent"} and not destination:
            raise ParityError("{} paired outcome has no destination".format(outcome["id"]))
        if classification == "pending":
            pending.append(outcome["id"])
        _strictly_sorted_unique(outcome["domains"], outcome["id"] + " domains")
        _strictly_sorted_unique(outcome["prerequisites"], outcome["id"] + " prerequisites")
        for side in ("source", "destination"):
            side_endpoints = outcome[side]
            keys = [(entry["line"], entry["commit"]) for entry in side_endpoints]
            if len(keys) != len(set(keys)):
                raise ParityError("{} repeats an endpoint".format(outcome["id"]))
            for entry in side_endpoints:
                key = (entry["line"], entry["commit"])
                if key in endpoints:
                    previous = endpoints[key]
                    raise ParityError(
                        "commit {}:{} occurs in both {} and {}".format(
                            key[0], key[1], previous[0], outcome["id"]
                        )
                    )
                endpoints[key] = (outcome["id"], entry["pull_request"])
    if pending:
        raise ParityError("delivered horizons cannot retain pending outcomes: {}".format(pending))

    exceptions = document["tree_exceptions"]
    exception_paths = [entry["path"] for entry in exceptions]
    _strictly_sorted_unique(exception_paths, "tree exception paths")
    for path in exception_paths:
        _safe_path(path)

    line_counts = {line: sum(1 for endpoint in endpoints if endpoint[0] == line) for line in horizons}
    if check_history:
        if root is None:
            raise ParityError("history validation requires a repository root")
        root = root.resolve()
        line = _line_identity(root)
        fork = document["fork"]["commit"]
        horizon = horizons[line]
        if _git(root, "rev-parse", "{}^{{commit}}".format(horizon)).strip() != horizon:
            raise ParityError("{} horizon object is unavailable".format(line))
        if _git(root, "merge-base", fork, horizon).strip() != fork:
            raise ParityError("{} horizon does not descend from the fork".format(line))
        merges = _git(root, "rev-list", "--merges", "{}..{}".format(fork, horizon)).splitlines()
        if merges:
            raise ParityError("{} audited range is not linear".format(line))
        observed = _git(root, "rev-list", "--reverse", "{}..{}".format(fork, horizon)).splitlines()
        recorded = [commit for endpoint_line, commit in endpoints if endpoint_line == line]
        if set(observed) != set(recorded):
            missing = sorted(set(observed) - set(recorded))
            extra = sorted(set(recorded) - set(observed))
            raise ParityError(
                "{} history coverage mismatch; missing={}, extra={}".format(line, missing, extra)
            )
        for commit in observed:
            outcome_id, pull_request = endpoints[(line, commit)]
            subject = _git(root, "show", "-s", "--format=%s", commit).strip()
            if not subject.endswith("(#{})".format(pull_request)):
                raise ParityError(
                    "{} commit {} does not bind pull request #{}".format(
                        outcome_id, commit, pull_request
                    )
                )

    return {
        "schema_version": document["schema_version"],
        "fork": document["fork"]["commit"],
        "horizons": dict(horizons),
        "outcomes": len(outcomes),
        "commits": sum(line_counts.values()),
        "commits_by_line": line_counts,
        "tree_exceptions": len(exceptions),
        "terminal_plan_state": terminal["state"],
        "terminal_commits_by_line": {
            line: len(terminal[line]["commits"]) for line in ("main", "1.x")
        },
    }


def load_and_validate(root: Path, *, check_history: bool = True) -> dict[str, Any]:
    root = root.resolve()
    schema_path = root / SCHEMA_PATH
    ledger_path = root / LEDGER_PATH
    try:
        schema = validate_schema(load_json(schema_path), SCHEMA_NAME)
        document = load_json(ledger_path)
        validate_instance(document, schema)
    except ContractError as error:
        raise ParityError(str(error)) from error
    canonical = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    try:
        source = ledger_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ParityError("cannot read parity ledger: {}".format(error)) from error
    if source != canonical:
        raise ParityError("parity ledger JSON is not canonically formatted")
    return validate_document(document, root=root, check_history=check_history)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json", action="store_true", help="emit a stable JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        report = load_and_validate(arguments.root)
    except ParityError as error:
        print("release-line parity: {}".format(error), file=sys.stderr)
        return 1
    if arguments.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(
            "Release-line parity ledger: {commits} commits in {outcomes} outcomes; "
            "{tree_exceptions} resulting-tree exceptions; terminal plan {terminal_plan_state}.".format(
                **report
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
