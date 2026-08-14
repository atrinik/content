#!/usr/bin/env python3
"""Validate the reviewed disposition of authored gameplay telemetry sites."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterator


MANIFEST_PATH = Path("contracts/scripted-gameplay-audit/v1.json")
METRIC_METHODS = frozenset({"MetricAdd", "MetricKeyedAdd", "MetricMarkUnique"})
CLASSIFICATIONS = frozenset(
    {"gameplay-journal", "aggregate-only", "operational/security-log", "not-recorded"}
)
METRIC_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
JOURNAL_REASON = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
IDENTITY_MAX = 255


class ScriptedGameplayAuditError(ValueError):
    """The authored scripted-gameplay audit is incomplete or malformed."""


def _safe_relative_path(root: Path, value: object) -> str:
    if not isinstance(value, str):
        raise ScriptedGameplayAuditError("audit paths must be strings")
    if "\\" in value or "\0" in value:
        raise ScriptedGameplayAuditError("audit path is not canonical POSIX: {!r}".format(value))
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or "." in path.parts or ".." in path.parts:
        raise ScriptedGameplayAuditError("unsafe audit path: {!r}".format(value))
    if not value.startswith("maps/") or not value.endswith(".py"):
        raise ScriptedGameplayAuditError("audit path is not authored map Python: {}".format(value))
    maps_root = (root / "maps").resolve()
    native = (root / value).resolve()
    if native == maps_root or maps_root not in native.parents:
        raise ScriptedGameplayAuditError("audit path escapes authored maps: {}".format(value))
    return value


def _literal_metric(call: ast.Call, path: str) -> str:
    if not call.args or not isinstance(call.args[0], ast.Constant) or not isinstance(
        call.args[0].value, str
    ):
        raise ScriptedGameplayAuditError(
            "{}:{} uses a dynamic metric identity".format(path, call.lineno)
        )
    return call.args[0].value


def _source_paths(root: Path) -> Iterator[Path]:
    maps_root = root / "maps"
    for source in sorted(maps_root.rglob("*.py")):
        relative = source.relative_to(maps_root)
        if relative.parts[:2] == ("python", "tests"):
            continue
        yield source


def _children(node: ast.AST) -> Iterator[tuple[str, ast.AST]]:
    for field, value in ast.iter_fields(node):
        if isinstance(value, ast.AST):
            yield field, value
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield "{}[{}]".format(field, index), item


def _context_sha256(node: ast.AST) -> str:
    serialized = ast.dump(node, annotate_fields=True, include_attributes=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _discover_source(root: Path, source: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    relative = source.relative_to(root).as_posix()
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as error:
        raise ScriptedGameplayAuditError(
            "cannot inspect authored Python {}: {}".format(relative, error)
        ) from error

    metrics: list[dict[str, str]] = []
    logs: list[dict[str, str]] = []
    direct_metric_attributes: set[int] = set()

    def visit(
        node: ast.AST,
        ast_path: str,
        scopes: tuple[str, ...],
        context_sha256: str,
    ) -> None:
        next_scopes = scopes
        next_context_sha256 = context_sha256
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            next_scopes = (*scopes, node.name)
            next_context_sha256 = _context_sha256(node)
        if isinstance(node, ast.Call):
            scope = ".".join(scopes) or "<module>"
            if isinstance(node.func, ast.Attribute) and node.func.attr in METRIC_METHODS:
                direct_metric_attributes.add(id(node.func))
                metrics.append(
                    {
                        "path": relative,
                        "ast_path": ast_path,
                        "scope": scope,
                        "context_sha256": context_sha256,
                        "method": node.func.attr,
                        "metric": _literal_metric(node, relative),
                    }
                )
            facility = None
            if isinstance(node.func, ast.Name) and node.func.id == "Logger":
                facility = "Logger"
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "Logger"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "Atrinik"
            ):
                facility = "Atrinik.Logger"
            elif isinstance(node.func, ast.Attribute) and node.func.attr == "log_add":
                facility = "Guild.log_add"
            if facility is not None:
                logs.append(
                    {
                        "path": relative,
                        "ast_path": ast_path,
                        "scope": scope,
                        "context_sha256": context_sha256,
                        "facility": facility,
                    }
                )
        for edge, child in _children(node):
            visit(
                child,
                "{}.{}".format(ast_path, edge) if ast_path else edge,
                next_scopes,
                next_context_sha256,
            )

    visit(tree, "", (), _context_sha256(tree))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in METRIC_METHODS:
            if id(node) not in direct_metric_attributes:
                raise ScriptedGameplayAuditError(
                    "{}:{} uses an indirect metric method reference".format(relative, node.lineno)
                )
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in METRIC_METHODS
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} names a metric method indirectly".format(relative, node.lineno)
            )
    return metrics, logs


def discover_sites(root: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return every exact authored metric and audit-log call occurrence."""

    metrics: list[dict[str, str]] = []
    logs: list[dict[str, str]] = []
    for source in _source_paths(root):
        source_metrics, source_logs = _discover_source(root, source)
        metrics.extend(source_metrics)
        logs.extend(source_logs)
    metrics.sort(key=lambda row: (row["path"], row["ast_path"]))
    logs.sort(key=lambda row: (row["path"], row["ast_path"]))
    return metrics, logs


def _require_text(row: dict[str, Any], field: str, context: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ScriptedGameplayAuditError("{} requires non-empty {}".format(context, field))
    return value


def _validate_identity(value: object, pattern: re.Pattern[str], context: str) -> str:
    if not isinstance(value, str) or not value.isascii():
        raise ScriptedGameplayAuditError("{} must be bounded ASCII".format(context))
    if not value or len(value) > IDENTITY_MAX or pattern.fullmatch(value) is None:
        raise ScriptedGameplayAuditError(
            "{} is invalid or exceeds {} characters".format(context, IDENTITY_MAX)
        )
    return value


def _validate_common_source(
    row: dict[str, Any], root: Path, context: str
) -> tuple[str, str, str]:
    source = _safe_relative_path(root, row["path"])
    ast_path = _require_text(row, "ast_path", context)
    scope = _require_text(row, "scope", context)
    if not (root / source).is_file():
        raise ScriptedGameplayAuditError("{} source is missing".format(context))
    return source, ast_path, scope


def load_and_validate(root: Path) -> dict[str, Any]:
    """Validate the closed manifest and its exact source inventory."""

    path = root / MANIFEST_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScriptedGameplayAuditError(
            "cannot load {}: {}".format(MANIFEST_PATH, error)
        ) from error
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "source_contexts",
        "metric_sites",
        "audit_like_sites",
    }:
        raise ScriptedGameplayAuditError("scripted gameplay audit must be a closed v1 object")
    if document["schema_version"] != 1:
        raise ScriptedGameplayAuditError("unsupported scripted gameplay audit schema")

    expected_contexts: dict[tuple[str, str], str] = {}
    context_rows = document["source_contexts"]
    if not isinstance(context_rows, list) or not context_rows:
        raise ScriptedGameplayAuditError("source_contexts must be a non-empty array")
    context_order: list[tuple[str, str]] = []
    for index, row in enumerate(context_rows):
        context = "source_contexts[{}]".format(index)
        if not isinstance(row, dict) or set(row) != {"path", "scope", "context_sha256"}:
            raise ScriptedGameplayAuditError("{} has an unknown or missing field".format(context))
        source = _safe_relative_path(root, row["path"])
        scope = _require_text(row, "scope", context)
        context_sha256 = row["context_sha256"]
        if (
            not isinstance(context_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", context_sha256) is None
        ):
            raise ScriptedGameplayAuditError("{} has an invalid context_sha256".format(context))
        if not (root / source).is_file():
            raise ScriptedGameplayAuditError("{} source is missing".format(context))
        key = (source, scope)
        context_order.append(key)
        expected_contexts[key] = context_sha256
    if context_order != sorted(context_order) or len(context_order) != len(set(context_order)):
        raise ScriptedGameplayAuditError("source_contexts must be sorted and unique")

    expected_metrics: list[dict[str, str]] = []
    rows = document["metric_sites"]
    if not isinstance(rows, list) or not rows:
        raise ScriptedGameplayAuditError("metric_sites must be a non-empty array")
    required = {
        "path",
        "ast_path",
        "scope",
        "method",
        "metric",
        "classification",
        "proposed_journal_reason",
        "event_rate",
        "rationale",
    }
    ordering: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        context = "metric_sites[{}]".format(index)
        if not isinstance(row, dict) or set(row) != required:
            raise ScriptedGameplayAuditError("{} has an unknown or missing field".format(context))
        source, ast_path, scope = _validate_common_source(row, root, context)
        context_sha256 = expected_contexts.get((source, scope))
        if context_sha256 is None:
            raise ScriptedGameplayAuditError("{} has no reviewed source context".format(context))
        method = row["method"]
        if method not in METRIC_METHODS:
            raise ScriptedGameplayAuditError("{} has an unknown metric method".format(context))
        metric = _validate_identity(row["metric"], METRIC_ID, "{} metric".format(context))
        classification = row["classification"]
        if classification not in CLASSIFICATIONS:
            raise ScriptedGameplayAuditError("{} has an unknown classification".format(context))
        reason = row["proposed_journal_reason"]
        if classification == "gameplay-journal":
            _validate_identity(reason, JOURNAL_REASON, "{} proposed reason".format(context))
        elif reason is not None:
            raise ScriptedGameplayAuditError(
                "{} must not propose a journal reason for {}".format(context, classification)
            )
        _require_text(row, "event_rate", context)
        _require_text(row, "rationale", context)
        expected_metrics.append(
            {
                "path": source,
                "ast_path": ast_path,
                "scope": scope,
                "context_sha256": context_sha256,
                "method": method,
                "metric": metric,
            }
        )
        ordering.append((source, ast_path))
    if ordering != sorted(ordering) or len(ordering) != len(set(ordering)):
        raise ScriptedGameplayAuditError("metric_sites must be sorted and occurrence-unique")

    expected_logs: list[dict[str, str]] = []
    audit_rows = document["audit_like_sites"]
    if not isinstance(audit_rows, list) or not audit_rows:
        raise ScriptedGameplayAuditError("audit_like_sites must be a non-empty array")
    audit_required = {
        "path",
        "ast_path",
        "scope",
        "facility",
        "classification",
        "event_rate",
        "rationale",
    }
    audit_order: list[tuple[str, str]] = []
    for index, row in enumerate(audit_rows):
        context = "audit_like_sites[{}]".format(index)
        if not isinstance(row, dict) or set(row) != audit_required:
            raise ScriptedGameplayAuditError("{} has an unknown or missing field".format(context))
        source, ast_path, scope = _validate_common_source(row, root, context)
        context_sha256 = expected_contexts.get((source, scope))
        if context_sha256 is None:
            raise ScriptedGameplayAuditError("{} has no reviewed source context".format(context))
        facility = _require_text(row, "facility", context)
        classification = row["classification"]
        if classification not in CLASSIFICATIONS:
            raise ScriptedGameplayAuditError("{} has an unknown classification".format(context))
        _require_text(row, "event_rate", context)
        _require_text(row, "rationale", context)
        expected_logs.append(
            {
                "path": source,
                "ast_path": ast_path,
                "scope": scope,
                "context_sha256": context_sha256,
                "facility": facility,
            }
        )
        audit_order.append((source, ast_path))
    if audit_order != sorted(audit_order) or len(audit_order) != len(set(audit_order)):
        raise ScriptedGameplayAuditError("audit_like_sites must be sorted and occurrence-unique")

    actual_metrics, actual_logs = discover_sites(root)
    actual_contexts = {
        (row["path"], row["scope"]): row["context_sha256"]
        for row in (*actual_metrics, *actual_logs)
    }
    if actual_contexts != expected_contexts:
        raise ScriptedGameplayAuditError(
            "source-context inventory differs: expected={} actual={}".format(
                expected_contexts, actual_contexts
            )
        )
    if actual_metrics != expected_metrics:
        raise ScriptedGameplayAuditError(
            "metric-site inventory differs: expected={} actual={}".format(
                expected_metrics, actual_metrics
            )
        )
    if actual_logs != expected_logs:
        raise ScriptedGameplayAuditError(
            "audit-like-site inventory differs: expected={} actual={}".format(
                expected_logs, actual_logs
            )
        )
    return {
        "metric_sites": len(actual_metrics),
        "metric_identities": len({row["metric"] for row in actual_metrics}),
        "audit_like_sites": len(actual_logs),
    }
