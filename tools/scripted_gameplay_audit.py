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
SENSITIVE_RECEIVER_NAMES = frozenset(
    {"Atrinik", "activator", "controller", "guild", "pl", "player"}
)
SENSITIVE_REFLECTIVE_NAMES = frozenset(
    (*METRIC_METHODS, "Eval", "Logger", "log_add", "print", "__getattribute__")
)
DYNAMIC_EXECUTION_NAMES = frozenset({"compile", "eval", "exec", "__import__"})
NAMESPACE_REFLECTION_NAMES = frozenset({"globals", "locals"})


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


def _static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _static_string(node.left)
        right = _static_string(node.right)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            part = _static_string(value)
            if part is None:
                return None
            parts.append(part)
        return "".join(parts)
    return None


def _sensitive_receiver(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    if isinstance(node, ast.Attribute):
        return _sensitive_receiver(node.value, aliases)
    if isinstance(node, ast.Subscript):
        return _sensitive_receiver(node.value, aliases)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_sensitive_receiver(value, aliases) for value in node.elts)
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            return node.func.attr == "Controller"
        if isinstance(node.func, ast.Name):
            if node.func.id == "type" and node.args:
                return _sensitive_receiver(node.args[0], aliases)
            return node.func.id in {"FindPlayer", "GetFirst", "Guild", "WhoIsActivator"}
    if isinstance(node, ast.IfExp):
        return _sensitive_receiver(node.body, aliases) or _sensitive_receiver(
            node.orelse, aliases
        )
    if isinstance(node, ast.BoolOp):
        return any(_sensitive_receiver(value, aliases) for value in node.values)
    return False


def _contains_sensitive_receiver(node: ast.AST, aliases: set[str]) -> bool:
    return any(_sensitive_receiver(child, aliases) for child in ast.walk(node))


def _loaded_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def _interactive_console_receiver(node: ast.AST, code_aliases: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "InteractiveConsole"
        and isinstance(node.value, ast.Name)
        and node.value.id in code_aliases
    )


def _propagate_alias_target(
    target: ast.AST,
    value: ast.AST,
    aliases: set[str],
) -> bool:
    if isinstance(target, ast.Name) and _sensitive_receiver(value, aliases):
        if target.id not in aliases:
            aliases.add(target.id)
            return True
        return False
    if isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (ast.Tuple, ast.List)):
        changed = False
        for target_item, value_item in zip(target.elts, value.elts):
            changed = _propagate_alias_target(target_item, value_item, aliases) or changed
        return changed
    return False


def _target_value_pairs(target: ast.AST, value: ast.AST) -> Iterator[tuple[str, ast.AST]]:
    """Yield statically paired assignment names for conservative rebinding checks."""

    if isinstance(target, ast.Name):
        yield target.id, value
    elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(
        value, (ast.Tuple, ast.List)
    ):
        for target_item, value_item in zip(target.elts, value.elts):
            yield from _target_value_pairs(target_item, value_item)


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
    direct_log_references: set[int] = set()
    direct_reflection_references: set[int] = set()
    sensitive_aliases = set(SENSITIVE_RECEIVER_NAMES)
    reflection_aliases = {"getattr", "vars"}
    logger_aliases = {"Logger"}
    print_aliases = {"print"}
    atrinik_aliases = {"Atrinik"}
    builtins_aliases = {"__builtins__", "builtins"}
    code_aliases = {"code"}
    atrinik_wildcard = False
    assignments: list[tuple[ast.AST, ast.AST, int]] = []
    ambiguous_sensitive_aliases: set[str] = set()
    for imported in ast.walk(tree):
        if isinstance(imported, ast.Import):
            for name in imported.names:
                if name.name == "builtins":
                    builtins_aliases.add(name.asname or name.name)
                if name.name == "Atrinik":
                    atrinik_aliases.add(name.asname or name.name)
                if name.name == "code":
                    code_aliases.add(name.asname or name.name)
        if isinstance(imported, ast.ImportFrom) and imported.module == "Atrinik":
            for name in imported.names:
                if name.name == "*":
                    atrinik_wildcard = True
                if name.name == "Logger":
                    logger_aliases.add(name.asname or name.name)
                if name.name == "print":
                    raise ScriptedGameplayAuditError(
                        "{}:{} aliases a reserved audit callable".format(
                            relative, imported.lineno
                        )
                    )
                if name.name == "Eval":
                    raise ScriptedGameplayAuditError(
                        "{}:{} aliases a reserved execution callable".format(
                            relative, imported.lineno
                        )
                    )
        if isinstance(imported, ast.ImportFrom) and imported.module == "code":
            if any(name.name in {"*", "InteractiveConsole"} for name in imported.names):
                raise ScriptedGameplayAuditError(
                    "{}:{} aliases a reserved execution facility".format(
                        relative, imported.lineno
                    )
                )
        if isinstance(imported, ast.ImportFrom) and imported.module == "builtins":
            if any(
                name.name in {"getattr", "print", "vars"} | DYNAMIC_EXECUTION_NAMES
                | NAMESPACE_REFLECTION_NAMES
                for name in imported.names
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} aliases a reserved reflective callable".format(
                        relative, imported.lineno
                    )
                )
        if isinstance(imported, ast.ImportFrom) and imported.module == "operator":
            if any(
                name.name in {"*", "attrgetter", "methodcaller"}
                for name in imported.names
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} aliases a reserved reflective callable".format(
                        relative, imported.lineno
                    )
                )
        if isinstance(imported, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            arguments = (
                [*imported.args.posonlyargs, *imported.args.args, *imported.args.kwonlyargs]
                + ([imported.args.vararg] if imported.args.vararg is not None else [])
                + ([imported.args.kwarg] if imported.args.kwarg is not None else [])
            )
            if any(
                argument.arg in logger_aliases | print_aliases
                for argument in arguments
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} shadows a reserved audit callable".format(relative, imported.lineno)
                )
        if isinstance(imported, ast.Assign):
            assignments.extend(
                (target, imported.value, imported.lineno) for target in imported.targets
            )
        elif isinstance(imported, ast.AnnAssign) and imported.value is not None:
            assignments.append((imported.target, imported.value, imported.lineno))
        elif isinstance(imported, ast.NamedExpr):
            assignments.append((imported.target, imported.value, imported.lineno))
    if atrinik_wildcard:
        for binding in ast.walk(tree):
            if (
                isinstance(binding, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and binding.name == "Eval"
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} shadows the wildcard Atrinik.Eval binding".format(
                        relative, binding.lineno
                    )
                )
            if isinstance(binding, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                arguments = (
                    [
                        *binding.args.posonlyargs,
                        *binding.args.args,
                        *binding.args.kwonlyargs,
                    ]
                    + ([binding.args.vararg] if binding.args.vararg is not None else [])
                    + ([binding.args.kwarg] if binding.args.kwarg is not None else [])
                )
                if any(argument.arg == "Eval" for argument in arguments):
                    raise ScriptedGameplayAuditError(
                        "{}:{} shadows the wildcard Atrinik.Eval binding".format(
                            relative, binding.lineno
                        )
                    )
            if (
                isinstance(binding, ast.Name)
                and isinstance(binding.ctx, (ast.Store, ast.Del))
                and binding.id == "Eval"
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} shadows the wildcard Atrinik.Eval binding".format(
                        relative, binding.lineno
                    )
                )
            if isinstance(binding, (ast.Import, ast.ImportFrom)) and any(
                (name.asname or name.name.split(".")[0]) == "Eval"
                for name in binding.names
                if name.name != "*"
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} shadows the wildcard Atrinik.Eval binding".format(
                        relative, binding.lineno
                    )
                )
    changed = True
    while changed:
        changed = False
        for target, value, lineno in assignments:
            for _name, assigned_value in _target_value_pairs(target, value):
                if isinstance(assigned_value, ast.Name):
                    if (
                        assigned_value.id in builtins_aliases
                        and _name not in builtins_aliases
                    ):
                        builtins_aliases.add(_name)
                        changed = True
                    if (
                        assigned_value.id in atrinik_aliases
                        and _name not in atrinik_aliases
                    ):
                        atrinik_aliases.add(_name)
                        changed = True
                    if assigned_value.id in code_aliases and _name not in code_aliases:
                        code_aliases.add(_name)
                        changed = True
                if (
                    isinstance(assigned_value, ast.Attribute)
                    and isinstance(assigned_value.value, ast.Name)
                    and assigned_value.value.id in builtins_aliases
                    and assigned_value.attr
                    in {"getattr", "vars"}
                    | DYNAMIC_EXECUTION_NAMES
                    | NAMESPACE_REFLECTION_NAMES
                ):
                    raise ScriptedGameplayAuditError(
                        "{}:{} aliases a reserved reflective callable".format(
                            relative, lineno
                        )
                    )
                if (
                    isinstance(assigned_value, ast.Attribute)
                    and assigned_value.attr == "InteractiveConsole"
                    and isinstance(assigned_value.value, ast.Name)
                    and assigned_value.value.id in code_aliases
                ):
                    raise ScriptedGameplayAuditError(
                        "{}:{} aliases a reserved execution facility".format(
                            relative, lineno
                        )
                    )
            if isinstance(target, ast.Name) and target.id in {"Logger", "print"}:
                raise ScriptedGameplayAuditError(
                    "{}:{} shadows a reserved audit callable".format(relative, lineno)
                )
            if (
                isinstance(target, ast.Name)
                and target.id == "guild"
                and not _sensitive_receiver(value, sensitive_aliases)
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} ambiguously rebinds the guild audit receiver".format(
                        relative, lineno
                    )
                )
            changed = _propagate_alias_target(target, value, sensitive_aliases) or changed
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in builtins_aliases
                and value.attr
                in {"getattr", "vars"}
                | DYNAMIC_EXECUTION_NAMES
                | NAMESPACE_REFLECTION_NAMES
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} aliases a reserved reflective callable".format(relative, lineno)
                )
            if (
                isinstance(value, ast.Attribute)
                and value.attr in {"get", "__getitem__"}
                and isinstance(value.value, ast.Call)
                and isinstance(value.value.func, ast.Name)
                and value.value.func.id in {"globals", "locals"}
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} aliases a reflective namespace lookup".format(relative, lineno)
                )
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in {"globals", "locals"}
            ) or (
                isinstance(value, ast.Name)
                and value.id in {"globals", "locals"}
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} aliases a reflective namespace".format(relative, lineno)
                )
            if (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and (
                    value.value.id in atrinik_aliases
                    and value.attr == "print"
                    or value.value.id in builtins_aliases
                    and value.attr
                    in {"print"} | DYNAMIC_EXECUTION_NAMES | NAMESPACE_REFLECTION_NAMES
                )
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} aliases a reserved audit callable".format(relative, lineno)
                )
            if not isinstance(target, ast.Name):
                continue
            if isinstance(value, ast.Name):
                if value.id in builtins_aliases and target.id not in builtins_aliases:
                    builtins_aliases.add(target.id)
                    changed = True
                if value.id in atrinik_aliases and target.id not in atrinik_aliases:
                    atrinik_aliases.add(target.id)
                    changed = True
                if value.id in code_aliases and target.id not in code_aliases:
                    code_aliases.add(target.id)
                    changed = True
                if value.id in reflection_aliases and target.id not in reflection_aliases:
                    reflection_aliases.add(target.id)
                    changed = True
                if value.id in logger_aliases and target.id not in logger_aliases:
                    logger_aliases.add(target.id)
                    changed = True
                if value.id in print_aliases and target.id not in print_aliases:
                    print_aliases.add(target.id)
                    changed = True
                if value.id in DYNAMIC_EXECUTION_NAMES:
                    raise ScriptedGameplayAuditError(
                        "{}:{} aliases a reserved reflective callable".format(relative, lineno)
                    )
            if target.id in print_aliases and not (
                isinstance(value, ast.Name) and value.id in print_aliases
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} ambiguously rebinds a print alias".format(relative, lineno)
                )
            if (
                isinstance(value, ast.Attribute)
                and value.attr == "Logger"
                and isinstance(value.value, ast.Name)
                and value.value.id == "Atrinik"
                and target.id not in logger_aliases
            ):
                logger_aliases.add(target.id)
                changed = True

    for target, value, lineno in assignments:
        for name, assigned_value in _target_value_pairs(target, value):
            if name in sensitive_aliases and not _sensitive_receiver(
                assigned_value, sensitive_aliases
            ):
                ambiguous_sensitive_aliases.add(name)

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
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                (*scopes, node.name) == ("Guild", "log_add")
            ):
                logs.append(
                    {
                        "path": relative,
                        "ast_path": ast_path,
                        "scope": "Guild.log_add",
                        "context_sha256": next_context_sha256,
                        "facility": "Guild.log_add sink",
                    }
                )
        if isinstance(node, ast.Call):
            scope = ".".join(scopes) or "<module>"
            if isinstance(node.func, ast.Attribute) and node.func.attr in METRIC_METHODS:
                if _loaded_names(node.func.value) & ambiguous_sensitive_aliases:
                    raise ScriptedGameplayAuditError(
                        "{}:{} uses an ambiguously rebound telemetry receiver".format(
                            relative, node.lineno
                        )
                    )
                if not _sensitive_receiver(node.func.value, sensitive_aliases):
                    raise ScriptedGameplayAuditError(
                        "{}:{} uses a reserved metric method on an unreviewed receiver".format(
                            relative, node.lineno
                        )
                    )
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
            if isinstance(node.func, ast.Name) and node.func.id in logger_aliases:
                facility = "Logger" if node.func.id == "Logger" else "Atrinik.Logger"
                direct_log_references.add(id(node.func))
            elif isinstance(node.func, ast.Name) and node.func.id in print_aliases:
                facility = "Python.print"
                direct_log_references.add(id(node.func))
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "Logger"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in atrinik_aliases
            ):
                facility = "Atrinik.Logger"
                direct_log_references.add(id(node.func))
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "print"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in builtins_aliases | atrinik_aliases
            ):
                facility = "Python.print"
                direct_log_references.add(id(node.func))
            elif (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "log_add"
                and _sensitive_receiver(node.func.value, sensitive_aliases)
            ):
                if _loaded_names(node.func.value) & ambiguous_sensitive_aliases:
                    raise ScriptedGameplayAuditError(
                        "{}:{} uses an ambiguously rebound telemetry receiver".format(
                            relative, node.lineno
                        )
                    )
                facility = "Guild.log_add"
                direct_log_references.add(id(node.func))
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
            if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
                logs.append(
                    {
                        "path": relative,
                        "ast_path": ast_path,
                        "scope": scope,
                        "context_sha256": context_sha256,
                        "facility": "Python.{}".format(node.func.id),
                    }
                )
                direct_log_references.add(id(node.func))
            if (
                atrinik_wildcard
                and isinstance(node.func, ast.Name)
                and node.func.id == "Eval"
            ):
                logs.append(
                    {
                        "path": relative,
                        "ast_path": ast_path,
                        "scope": scope,
                        "context_sha256": context_sha256,
                        "facility": "Atrinik.Eval",
                    }
                )
                direct_log_references.add(id(node.func))
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in builtins_aliases
                and node.func.attr in {"eval", "exec"}
            ):
                logs.append(
                    {
                        "path": relative,
                        "ast_path": ast_path,
                        "scope": scope,
                        "context_sha256": context_sha256,
                        "facility": "Python.{}".format(node.func.attr),
                    }
                )
                direct_log_references.add(id(node.func))
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "push"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "InteractiveConsole"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id in code_aliases
            ):
                logs.append(
                    {
                        "path": relative,
                        "ast_path": ast_path,
                        "scope": scope,
                        "context_sha256": context_sha256,
                        "facility": "Python.InteractiveConsole.push",
                    }
                )
                direct_log_references.add(id(node.func))
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in {"getattr", "vars"}
            ):
                direct_reflection_references.add(id(node.func))
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
            (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in logger_aliases
            )
            or (
                isinstance(node, ast.Attribute)
                and (
                    (
                        node.attr == "Logger"
                    )
                    or (
                        node.attr == "log_add"
                    )
                    or (
                        node.attr == "print"
                        and isinstance(node.value, ast.Name)
                        and node.value.id in builtins_aliases | atrinik_aliases
                    )
                    or (
                        node.attr in {"eval", "exec"}
                        and isinstance(node.value, ast.Name)
                        and node.value.id in builtins_aliases
                    )
                    or (
                        node.attr == "Eval"
                        and isinstance(node.value, ast.Name)
                        and node.value.id in atrinik_aliases
                    )
                    or (
                        node.attr == "push"
                        and isinstance(node.value, ast.Attribute)
                        and node.value.attr == "InteractiveConsole"
                        and isinstance(node.value.value, ast.Name)
                        and node.value.value.id in code_aliases
                    )
                )
            )
        ) and id(node) not in direct_log_references:
            raise ScriptedGameplayAuditError(
                "{}:{} uses an indirect audit-log reference".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id in {"getattr", "vars", "print"} | DYNAMIC_EXECUTION_NAMES
            and id(node) not in direct_reflection_references
            and id(node) not in direct_log_references
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} aliases a reserved reflective callable".format(relative, node.lineno)
            )
        if (
            atrinik_wildcard
            and isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == "Eval"
            and id(node) not in direct_log_references
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} aliases a reserved execution callable".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in reflection_aliases
            and any(isinstance(argument, ast.Starred) for argument in node.args)
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} uses reflective telemetry access".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in reflection_aliases
            and node.func.id != "vars"
            and len(node.args) >= 2
        ):
            reflected_name = _static_string(node.args[1])
            if reflected_name in (
                SENSITIVE_REFLECTIVE_NAMES
                | DYNAMIC_EXECUTION_NAMES
                | NAMESPACE_REFLECTION_NAMES
            ) or (
                reflected_name == "InteractiveConsole"
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in code_aliases
            ) or (
                reflected_name == "push"
                and _interactive_console_receiver(node.args[0], code_aliases)
            ) or (
                reflected_name is None
                and (
                    _sensitive_receiver(node.args[0], sensitive_aliases)
                    or (
                        isinstance(node.args[0], ast.Name)
                        and node.args[0].id in builtins_aliases
                    )
                    or (
                        isinstance(node.args[0], ast.Name)
                        and node.args[0].id in code_aliases
                    )
                    or _interactive_console_receiver(node.args[0], code_aliases)
                )
            ):
                raise ScriptedGameplayAuditError(
                    "{}:{} uses reflective telemetry access".format(relative, node.lineno)
                )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in reflection_aliases
            and node.func.id != "getattr"
            and node.args
            and (
                _sensitive_receiver(node.args[0], sensitive_aliases)
                or (
                    isinstance(node.args[0], ast.Name)
                    and node.args[0].id in builtins_aliases
                )
                or (
                    isinstance(node.args[0], ast.Name)
                    and node.args[0].id in code_aliases
                )
            )
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} uses reflective telemetry access".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in builtins_aliases
            and node.func.attr
            in {"compile", "getattr", "vars", "__import__"}
            | NAMESPACE_REFLECTION_NAMES
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} uses qualified reflective access".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "__getattribute__"
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} uses reflective telemetry access".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "__dict__"
            and (
                _contains_sensitive_receiver(node.value, sensitive_aliases)
                or (
                    isinstance(node.value, ast.Name)
                    and node.value.id in builtins_aliases | code_aliases
                )
                or _interactive_console_receiver(node.value, code_aliases)
            )
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} uses reflective telemetry access".format(relative, node.lineno)
            )
        if isinstance(node, ast.Attribute) and node.attr in {"attrgetter", "methodcaller"}:
            raise ScriptedGameplayAuditError(
                "{}:{} uses reflective attribute construction".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "__dict__"
            and _static_string(node.slice)
            in SENSITIVE_REFLECTIVE_NAMES
            | DYNAMIC_EXECUTION_NAMES
            | {"attrgetter", "methodcaller"}
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} uses reflective telemetry access".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Subscript)
            and (
                (
                    isinstance(node.value, ast.Name)
                    and node.value.id == "__builtins__"
                )
                or (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id in {"globals", "locals"}
                )
            )
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} uses reflective namespace access".format(relative, node.lineno)
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"get", "__getitem__"}
            and (
                (
                    isinstance(node.func.value, ast.Call)
                    and isinstance(node.func.value.func, ast.Name)
                    and node.func.value.func.id in {"globals", "locals"}
                )
                or (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id in builtins_aliases
                )
            )
        ):
            raise ScriptedGameplayAuditError(
                "{}:{} uses reflective namespace access".format(relative, node.lineno)
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
        if classification not in {"operational/security-log", "not-recorded"}:
            raise ScriptedGameplayAuditError(
                "{} audit facility must remain operational or not recorded".format(context)
            )
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
