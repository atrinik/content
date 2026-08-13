#!/usr/bin/env python3
"""Validate Atrinik's deterministic cross-release-line parity ledger."""

from __future__ import annotations

import argparse
from collections import Counter
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
from tools.content_catalog.loaders import load_catalog  # noqa: E402
from tools.content_core.parser import LegacyParser  # noqa: E402


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
        if [entry["issue"] for entry in commits] != [137, 139, 166]:
            raise ParityError(
                "{} terminal order must be #137 then #139 then #166".format(line)
            )
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


def _load_ledger(root: Path) -> Mapping[str, Any]:
    try:
        value = load_json(root.resolve() / LEDGER_PATH)
    except ContractError as error:
        raise ParityError(str(error)) from error
    if not isinstance(value, dict):
        raise ParityError("parity ledger root must be an object")
    return value


def _tree_blobs(root: Path) -> dict[str, tuple[str, str, str]]:
    blobs: dict[str, tuple[str, str, str]] = {}
    for line in _git(root, "ls-tree", "-r", "HEAD").splitlines():
        metadata, separator, path = line.partition("\t")
        parts = metadata.split()
        if not separator or len(parts) != 3 or parts[1] != "blob":
            raise ParityError("malformed git tree record")
        if path in blobs:
            raise ParityError("duplicate tracked path: {}".format(path))
        blobs[path] = (parts[0], parts[1], parts[2])
    return blobs


def _blob_bytes(root: Path, entry: tuple[str, str, str]) -> bytes:
    mode, object_type, object_id = entry
    if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
        raise ParityError(
            "unsupported tracked object {} {} {}".format(mode, object_type, object_id)
        )
    try:
        return subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", object_id],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise ParityError(
            "cannot read committed blob {}: {}".format(object_id, detail)
        ) from error


def _field_value(field: Any) -> str:
    value = field.typed_value if field.typed_value is not None else field.value
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _semantic_ads_signature(source: bytes, *, path: str, schema_root: Path) -> Any:
    format_name = "archetype" if path.startswith("arch/") else "map"
    document = LegacyParser(schema_root).parse(source, path=path, format_name=format_name)
    errors = sorted(
        diagnostic["code"]
        for diagnostic in document.diagnostics
        if diagnostic["severity"] == "error"
    )
    if errors:
        raise ParityError("{} has lossless-parser errors: {}".format(path, errors))

    def node_signature(handle: str) -> Any:
        node = document.node(handle)
        fields = sorted(
            (field.name.casefold(), field.value_kind, _field_value(field))
            for field in node.fields
        )
        messages = [(message.text, message.terminated) for message in node.messages]
        children = [node_signature(child) for child in node.child_handles]
        return (node.kind, node.name, fields, messages, children)

    return [node_signature(handle) for handle in document.top_level_handles]


def evaluate_tree_differences(
    main_files: Mapping[str, bytes | None],
    one_files: Mapping[str, bytes | None],
    exceptions: list[Mapping[str, Any]],
    *,
    schema_root: Path | None = None,
    observed_paths: set[str] | None = None,
) -> dict[str, int]:
    """Classify a supplied resulting-tree delta for tests and the live audit."""

    paths = set(main_files) | set(one_files)
    computed = {
        path
        for path in paths
        if path not in main_files
        or path not in one_files
        or main_files[path] != one_files[path]
    }
    observed = computed if observed_paths is None else set(observed_paths)
    if not computed <= observed:
        raise ParityError("authoritative tree differences omit changed bytes")
    if not observed <= paths:
        raise ParityError("authoritative tree differences name unavailable paths")
    exception_by_path = {entry["path"]: entry for entry in exceptions}
    if len(exception_by_path) != len(exceptions):
        raise ParityError("duplicate resulting-tree exception")
    unclassified = sorted(observed - set(exception_by_path))
    stale = sorted(set(exception_by_path) - observed)
    if unclassified:
        raise ParityError("unclassified resulting-tree differences: {}".format(unclassified))
    if stale:
        raise ParityError("stale resulting-tree exceptions: {}".format(stale))

    semantic_equal = 0
    for path in sorted(observed):
        entry = exception_by_path[path]
        if entry["classification"] != "equivalent" or entry["domain"] != "authored":
            continue
        left = main_files.get(path)
        right = one_files.get(path)
        if left is None or right is None:
            raise ParityError("equivalent authored path is absent on one line: {}".format(path))
        if not (path.startswith("arch/") and path.endswith(".arc")):
            raise ParityError("equivalent authored path lacks a semantic comparator: {}".format(path))
        if schema_root is None:
            raise ParityError("authored semantic comparison requires a schema root")
        if _semantic_ads_signature(left, path=path, schema_root=schema_root) != _semantic_ads_signature(
            right, path=path, schema_root=schema_root
        ):
            raise ParityError("equivalent authored values changed: {}".format(path))
        semantic_equal += 1
    return {
        "differences": len(observed),
        "exceptions": len(exception_by_path),
        "semantic_equal_authored": semantic_equal,
    }


def _catalog_identity(root: Path) -> tuple[dict[Any, Any], Counter[Any]]:
    catalog = load_catalog(root)
    if catalog.has_errors:
        errors = [item.format() for item in catalog.diagnostics if item.severity == "error"]
        raise ParityError("content catalog has errors: {}".format(errors[:10]))
    definitions = {
        (definition.content_id.domain, definition.content_id.key): (
            definition.location.path,
            json.dumps(definition.metadata, sort_keys=True, separators=(",", ":")),
        )
        for definition in catalog.definitions
    }
    references: Counter[Any] = Counter()
    for reference in catalog.references:
        source = None
        if reference.source is not None:
            source = (reference.source.domain, reference.source.key)
        references[
            (
                source,
                reference.field,
                reference.key,
                reference.allowed_domains,
                reference.location.path,
            )
        ] += 1
    return definitions, references


def _catalog_audit(main_root: Path, one_root: Path, exception_paths: set[str]) -> dict[str, int]:
    main_definitions, main_references = _catalog_identity(main_root)
    one_definitions, one_references = _catalog_identity(one_root)
    definition_delta = set(main_definitions) ^ set(one_definitions)
    changed_definitions = {
        identity
        for identity in set(main_definitions) & set(one_definitions)
        if main_definitions[identity] != one_definitions[identity]
    }
    for identity in sorted(definition_delta | changed_definitions):
        paths = set()
        if identity in main_definitions:
            paths.add(main_definitions[identity][0])
        if identity in one_definitions:
            paths.add(one_definitions[identity][0])
        if not paths or not paths <= exception_paths:
            raise ParityError(
                "unclassified catalog definition difference {} at {}".format(identity, sorted(paths))
            )

    reference_delta = (main_references - one_references) + (one_references - main_references)
    for reference in reference_delta:
        path = reference[4]
        if path not in exception_paths:
            raise ParityError(
                "unclassified catalog reference difference at {}: {}".format(path, reference)
            )
    return {
        "definitions_main": len(main_definitions),
        "definitions_1x": len(one_definitions),
        "definition_differences": len(definition_delta | changed_definitions),
        "reference_differences": sum(reference_delta.values()),
    }


def _patch_id(root: Path, commit: str) -> str:
    try:
        patch = subprocess.run(
            ["git", "-C", str(root), "show", "--pretty=format:", "--binary", commit],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        result = subprocess.run(
            ["git", "patch-id", "--stable"],
            input=patch,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.decode("ascii").split()
    except (subprocess.CalledProcessError, UnicodeError) as error:
        raise ParityError("cannot compute stable patch ID for {}".format(commit)) from error
    if len(result) < 2:
        raise ParityError("commit {} has no stable patch ID".format(commit))
    return result[0]


def _exact_patch_audit(
    document: Mapping[str, Any], roots: Mapping[str, Path]
) -> dict[str, int]:
    exact = 0
    for outcome in document["outcomes"]:
        if outcome["classification"] != "exact":
            continue
        patch_ids = {
            _patch_id(roots[endpoint["line"]], endpoint["commit"])
            for side in ("source", "destination")
            for endpoint in outcome[side]
        }
        if len(patch_ids) != 1:
            raise ParityError("{} exact patches differ".format(outcome["id"]))
        exact += 1
    return {"exact_outcomes": exact}


def _terminal_audit(
    root: Path,
    document: Mapping[str, Any],
    *,
    allow_candidate: bool,
) -> dict[str, Any]:
    line = _line_identity(root)
    terminal = document["terminal_plan"]
    if terminal["state"] != "declared":
        raise ParityError("terminal plan is not durably declared")
    plan = terminal[line]
    suffix = _git(
        root, "rev-list", "--reverse", "{}..HEAD".format(plan["horizon"])
    ).splitlines()
    if len(suffix) != len(plan["commits"]):
        raise ParityError(
            "{} terminal suffix length is {}; expected {}".format(
                line, len(suffix), len(plan["commits"])
            )
        )
    for commit, expected in zip(suffix, plan["commits"]):
        paths = sorted(
            _git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).splitlines()
        )
        if paths != expected["paths"]:
            raise ParityError(
                "{} ordinal {} paths differ; observed={}, expected={}".format(
                    line, expected["ordinal"], paths, expected["paths"]
                )
            )
        subject = _git(root, "show", "-s", "--format=%s", commit).strip()
        marker = "(#{})".format(expected["pull_request"])
        if subject.endswith(marker):
            continue
        if not allow_candidate:
            raise ParityError(
                "{} ordinal {} is not bound to PR #{}".format(
                    line, expected["ordinal"], expected["pull_request"]
                )
            )
        if subject.endswith(")") and "(#" in subject:
            raise ParityError(
                "{} ordinal {} is bound to the wrong pull request".format(
                    line, expected["ordinal"]
                )
            )
    return {"line": line, "commits": suffix, "candidate": allow_candidate}


def audit_release_lines(
    root: Path,
    other_root: Path,
    *,
    allow_candidate_terminal: bool = False,
) -> dict[str, Any]:
    """Run the full local, deterministic, read-only cross-line audit."""

    root = root.resolve()
    other_root = other_root.resolve()
    root_line = _line_identity(root)
    other_line = _line_identity(other_root)
    if root_line == other_line or {root_line, other_line} != {"main", "1.x"}:
        raise ParityError("--other-root must name the opposite release line")
    roots = {root_line: root, other_line: other_root}
    for line, line_root in roots.items():
        if _git(line_root, "status", "--porcelain").strip():
            raise ParityError("{} audit root is dirty".format(line))
        load_and_validate(line_root)

    main_document = _load_ledger(roots["main"])
    one_document = _load_ledger(roots["1.x"])
    if main_document != one_document:
        raise ParityError("release-line ledgers are not identical")
    document = main_document

    main_blobs = _tree_blobs(roots["main"])
    one_blobs = _tree_blobs(roots["1.x"])
    differing_paths = {
        path
        for path in set(main_blobs) | set(one_blobs)
        if main_blobs.get(path) != one_blobs.get(path)
    }
    main_files = {
        path: _blob_bytes(roots["main"], main_blobs[path]) if path in main_blobs else None
        for path in differing_paths
    }
    one_files = {
        path: _blob_bytes(roots["1.x"], one_blobs[path]) if path in one_blobs else None
        for path in differing_paths
    }
    tree_report = evaluate_tree_differences(
        main_files,
        one_files,
        document["tree_exceptions"],
        schema_root=roots["main"],
        observed_paths=differing_paths,
    )
    exception_paths = {entry["path"] for entry in document["tree_exceptions"]}
    return {
        "schema_version": 1,
        "fork": document["fork"]["commit"],
        "horizons": dict(document["horizons"]),
        "tree": tree_report,
        "catalog": _catalog_audit(roots["main"], roots["1.x"], exception_paths),
        "patches": _exact_patch_audit(document, roots),
        "terminal": {
            line: _terminal_audit(
                line_root, document, allow_candidate=allow_candidate_terminal
            )
            for line, line_root in sorted(roots.items())
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--other-root",
        type=Path,
        help="opposite release-line checkout for the full semantic audit",
    )
    parser.add_argument(
        "--candidate-terminal",
        action="store_true",
        help="accept unmerged candidate subjects while still enforcing suffix order and paths",
    )
    parser.add_argument("--json", action="store_true", help="emit a stable JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.other_root is None:
            if arguments.candidate_terminal:
                raise ParityError("--candidate-terminal requires --other-root")
            report = load_and_validate(arguments.root)
        else:
            report = audit_release_lines(
                arguments.root,
                arguments.other_root,
                allow_candidate_terminal=arguments.candidate_terminal,
            )
    except ParityError as error:
        print("release-line parity: {}".format(error), file=sys.stderr)
        return 1
    if arguments.json:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    elif arguments.other_root is not None:
        print(
            "Release-line semantic parity: {differences} classified tree differences; "
            "{semantic_equal_authored} authored order-only equivalences; "
            "{exact_outcomes} exact patch outcomes.".format(
                exact_outcomes=report["patches"]["exact_outcomes"],
                **report["tree"],
            )
        )
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
