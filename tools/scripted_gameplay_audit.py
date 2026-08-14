#!/usr/bin/env python3
"""Validate the reviewed disposition of authored gameplay telemetry sites."""

from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any


MANIFEST_PATH = Path("maps/python/scripted-gameplay-audit-v1.json")
METRIC_METHODS = frozenset({"MetricAdd", "MetricKeyedAdd", "MetricMarkUnique"})
CLASSIFICATIONS = frozenset(
    {"gameplay-journal", "aggregate-only", "operational/security-log", "not-recorded"}
)
METRIC_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
JOURNAL_REASON = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")


class ScriptedGameplayAuditError(ValueError):
    """The authored scripted-gameplay audit is incomplete or malformed."""


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str):
        raise ScriptedGameplayAuditError("audit paths must be strings")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or "." in path.parts or ".." in path.parts:
        raise ScriptedGameplayAuditError("unsafe audit path: {!r}".format(value))
    if not value.startswith("maps/python/") or not value.endswith(".py"):
        raise ScriptedGameplayAuditError("audit path is not authored Python: {}".format(value))
    return value


def _literal_metric(call: ast.Call, path: str) -> str:
    if not call.args or not isinstance(call.args[0], ast.Constant) or not isinstance(
        call.args[0].value, str
    ):
        raise ScriptedGameplayAuditError(
            "{}:{} uses a dynamic metric identity".format(path, call.lineno)
        )
    return call.args[0].value


def discover_metric_sites(root: Path) -> Counter[tuple[str, str, str]]:
    """Return exact authored metric call counts, excluding test fixtures."""

    sites: Counter[tuple[str, str, str]] = Counter()
    python_root = root / "maps" / "python"
    for source in sorted(python_root.rglob("*.py")):
        relative = source.relative_to(root).as_posix()
        if "tests" in source.relative_to(python_root).parts:
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=relative)
        except (OSError, UnicodeError, SyntaxError) as error:
            raise ScriptedGameplayAuditError(
                "cannot inspect authored Python {}: {}".format(relative, error)
            ) from error
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in METRIC_METHODS:
                continue
            sites[(relative, node.func.attr, _literal_metric(node, relative))] += 1
    return sites


def _require_text(row: dict[str, Any], field: str, context: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ScriptedGameplayAuditError("{} requires non-empty {}".format(context, field))
    return value


def load_and_validate(root: Path) -> dict[str, Any]:
    """Validate the closed manifest and its exact source inventory."""

    path = root / MANIFEST_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ScriptedGameplayAuditError("cannot load {}: {}".format(MANIFEST_PATH, error)) from error
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "metric_sites",
        "audit_like_sites",
    }:
        raise ScriptedGameplayAuditError("scripted gameplay audit must be a closed v1 object")
    if document["schema_version"] != 1:
        raise ScriptedGameplayAuditError("unsupported scripted gameplay audit schema")

    expected: Counter[tuple[str, str, str]] = Counter()
    ordering: list[tuple[str, str, str]] = []
    rows = document["metric_sites"]
    if not isinstance(rows, list) or not rows:
        raise ScriptedGameplayAuditError("metric_sites must be a non-empty array")
    required = {
        "path",
        "method",
        "metric",
        "count",
        "classification",
        "journal_reason",
        "event_rate",
        "rationale",
    }
    for index, row in enumerate(rows):
        context = "metric_sites[{}]".format(index)
        if not isinstance(row, dict) or set(row) != required:
            raise ScriptedGameplayAuditError("{} has an unknown or missing field".format(context))
        source = _safe_relative_path(row["path"])
        method = row["method"]
        metric = row["metric"]
        count = row["count"]
        classification = row["classification"]
        if method not in METRIC_METHODS:
            raise ScriptedGameplayAuditError("{} has an unknown metric method".format(context))
        if not isinstance(metric, str) or not METRIC_ID.fullmatch(metric):
            raise ScriptedGameplayAuditError("{} has an invalid metric identity".format(context))
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ScriptedGameplayAuditError("{} count must be a positive integer".format(context))
        if classification not in CLASSIFICATIONS:
            raise ScriptedGameplayAuditError("{} has an unknown classification".format(context))
        reason = row["journal_reason"]
        if classification == "gameplay-journal":
            if not isinstance(reason, str) or not JOURNAL_REASON.fullmatch(reason):
                raise ScriptedGameplayAuditError(
                    "{} requires a bounded journal reason".format(context)
                )
        elif reason is not None:
            raise ScriptedGameplayAuditError(
                "{} must not invent a journal reason for {}".format(context, classification)
            )
        _require_text(row, "event_rate", context)
        _require_text(row, "rationale", context)
        key = (source, method, metric)
        ordering.append(key)
        expected[key] += count
    if ordering != sorted(ordering) or len(ordering) != len(set(ordering)):
        raise ScriptedGameplayAuditError("metric_sites must be sorted and unique")

    actual = discover_metric_sites(root)
    if actual != expected:
        missing = sorted((expected - actual).elements())
        unreviewed = sorted((actual - expected).elements())
        raise ScriptedGameplayAuditError(
            "metric-site inventory differs: missing={} unreviewed={}".format(missing, unreviewed)
        )

    audit_rows = document["audit_like_sites"]
    if not isinstance(audit_rows, list):
        raise ScriptedGameplayAuditError("audit_like_sites must be an array")
    audit_order: list[tuple[str, str]] = []
    audit_required = {"path", "facility", "classification", "event_rate", "rationale"}
    for index, row in enumerate(audit_rows):
        context = "audit_like_sites[{}]".format(index)
        if not isinstance(row, dict) or set(row) != audit_required:
            raise ScriptedGameplayAuditError("{} has an unknown or missing field".format(context))
        source = _safe_relative_path(row["path"])
        facility = _require_text(row, "facility", context)
        classification = row["classification"]
        if classification not in CLASSIFICATIONS:
            raise ScriptedGameplayAuditError("{} has an unknown classification".format(context))
        if not (root / source).is_file():
            raise ScriptedGameplayAuditError("{} source is missing".format(context))
        _require_text(row, "event_rate", context)
        _require_text(row, "rationale", context)
        audit_order.append((source, facility))
    if audit_order != sorted(audit_order) or len(audit_order) != len(set(audit_order)):
        raise ScriptedGameplayAuditError("audit_like_sites must be sorted and unique")

    return {
        "metric_sites": sum(actual.values()),
        "metric_identities": len(actual),
        "audit_like_sites": len(audit_rows),
    }
