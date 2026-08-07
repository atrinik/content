"""Dry-run-first, conflict-safe multi-file authored-content transactions."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping, Optional, Sequence

from tools.content_contracts.contracts import (
    ContractError,
    confined_file,
    safe_relative_path,
)
from tools.syntax_evaluation.limits import DEFAULT_LIMITS

from .errors import (
    ContentConflictError,
    ContentCoreError,
    ContentSafetyError,
    ContentSyntaxError,
)
from .operations import (
    FieldRegistry,
    apply_edits,
    operation_edits,
    result_digest,
    unified_diff,
)
from .parser import PACKAGE_ROOT, parse_bytes


MAX_TRANSACTION_FILES = 64
MAX_TRANSACTION_OPERATIONS = 10_000
SOURCE_ROOT_MARKERS = (
    "arch/COPYING",
    "maps/COPYING",
    "schemas/authored-content-v1/source.json",
    "tools/COPYING",
)
OUTPUT_PATH_PARTS = {
    ".atrinik",
    "build",
    "collected",
    "dist",
    "generated",
    "package",
    "packaged",
    "runtime",
    "server-data",
}


@dataclass(frozen=True)
class PreparedFile:
    path: Path
    relative: str
    format_name: str
    before: bytes
    after: bytes
    operation_count: int

    def result(self) -> Mapping[str, Any]:
        return {
            "path": self.relative,
            "before_sha256": result_digest(self.before),
            "after_sha256": result_digest(self.after),
            "operation_count": self.operation_count,
            "diff": unified_diff(self.relative, self.before, self.after),
        }


@dataclass(frozen=True)
class PreparedTransaction:
    files: Sequence[PreparedFile]

    def result(self, *, dry_run: bool, applied: bool) -> Mapping[str, Any]:
        return {
            "schema_version": 1,
            "kind": "transaction-result",
            "dry_run": dry_run,
            "applied": applied,
            "files": [item.result() for item in self.files],
            "diagnostics": [],
        }


def _safe_target(root: Path, relative: object, format_name: object) -> Path:
    try:
        portable = safe_relative_path(relative, "transaction path")
    except ContractError as error:
        raise ContentSafetyError(str(error)) from error
    parts = Path(portable).parts
    if not parts or parts[0] not in ("arch", "maps"):
        raise ContentSafetyError(
            "writes are limited to authored arch/ and maps/ sources"
        )
    blocked = next(
        (part for part in parts[1:] if part.casefold() in OUTPUT_PATH_PARTS), None
    )
    if blocked is not None:
        raise ContentSafetyError(
            "transaction target uses reserved output path component: {}".format(
                blocked
            )
        )
    if format_name not in ("archetype", "map"):
        raise ContentCoreError(
            "transaction format must be archetype or map",
            code="unsupported-content-format",
        )
    if format_name == "archetype" and (
        parts[0] != "arch" or Path(portable).suffix != ".arc"
    ):
        raise ContentSafetyError(
            "archetype transactions require an authored arch/*.arc target"
        )
    if format_name == "map" and parts[0] != "maps":
        raise ContentSafetyError(
            "map transactions require an authored maps/ target"
        )
    try:
        return confined_file(root, portable, "authored transaction target")
    except ContractError as error:
        raise ContentSafetyError(str(error)) from error


def _verify_source_root(root: Path) -> None:
    for relative in SOURCE_ROOT_MARKERS:
        path = root.joinpath(*Path(relative).parts)
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ContentSafetyError(
                "transaction root is not an Atrinik authored source tree; "
                "missing marker {}".format(relative),
                code="non-authored-content-root",
            )


def prepare_transaction(
    root: Path,
    transaction: object,
    *,
    schema_root: Path = PACKAGE_ROOT,
) -> PreparedTransaction:
    """Validate every precondition and result before performing any write."""

    root = root.resolve(strict=True)
    if not isinstance(transaction, dict) or set(transaction) != {
        "schema_version",
        "kind",
        "files",
    }:
        raise ContentCoreError(
            "transaction root must be a closed v1 object",
            code="transaction-shape",
        )
    if (
        transaction["schema_version"] != 1
        or transaction["kind"] != "content-transaction"
    ):
        raise ContentCoreError(
            "transaction identity is unsupported",
            code="transaction-version",
        )
    _verify_source_root(root)
    files = transaction["files"]
    if (
        not isinstance(files, list)
        or not files
        or len(files) > MAX_TRANSACTION_FILES
    ):
        raise ContentCoreError(
            "transaction must contain 1..{} files".format(MAX_TRANSACTION_FILES),
            code="transaction-file-count",
        )
    paths = [item.get("path") if isinstance(item, dict) else None for item in files]
    if any(not isinstance(path, str) for path in paths) or paths != sorted(set(paths)):
        raise ContentCoreError(
            "transaction file paths must be sorted and unique",
            code="transaction-path-order",
        )

    registry = FieldRegistry(schema_root)
    prepared = []
    total_bytes = 0
    total_result_bytes = 0
    total_operations = 0
    for file_entry in files:
        expected = {"path", "format", "base_sha256", "operations"}
        if not isinstance(file_entry, dict) or set(file_entry) != expected:
            raise ContentCoreError(
                "transaction file must contain exactly: {}".format(
                    ", ".join(sorted(expected))
                ),
                code="transaction-file-shape",
            )
        relative = file_entry["path"]
        format_name = file_entry["format"]
        path = _safe_target(root, relative, format_name)
        before = path.read_bytes()
        total_bytes += len(before)
        if total_bytes > DEFAULT_LIMITS.max_input_bytes:
            raise ContentCoreError(
                "transaction source bytes exceed the shared input limit",
                code="transaction-size-limit",
            )
        if file_entry["base_sha256"] != result_digest(before):
            raise ContentConflictError(
                "base digest does not match {}".format(relative),
                code="stale-file-digest",
            )
        operations = file_entry["operations"]
        if not isinstance(operations, list) or not operations:
            raise ContentCoreError(
                "each transaction file requires at least one operation",
                code="empty-file-operations",
            )
        total_operations += len(operations)
        if total_operations > MAX_TRANSACTION_OPERATIONS:
            raise ContentCoreError(
                "transaction exceeds the operation count limit",
                code="transaction-operation-limit",
            )
        document = parse_bytes(
            before,
            path=relative,
            format_name=format_name,
            schema_root=schema_root,
        )
        if not document.valid:
            raise ContentSyntaxError(
                "transaction source is not valid: {}".format(relative),
                diagnostics=document.diagnostics,
            )
        edits = operation_edits(document, operations, registry)
        after = apply_edits(before, edits)
        total_result_bytes += len(after)
        if total_result_bytes > DEFAULT_LIMITS.max_input_bytes:
            raise ContentCoreError(
                "transaction result bytes exceed the shared input limit",
                code="transaction-result-size-limit",
            )
        result = parse_bytes(
            after,
            path=relative,
            format_name=format_name,
            schema_root=schema_root,
        )
        if not result.valid:
            raise ContentSyntaxError(
                "transaction result is not valid: {}".format(relative),
                code="invalid-transaction-result",
                diagnostics=result.diagnostics,
            )
        prepared.append(
            PreparedFile(
                path=path,
                relative=relative,
                format_name=format_name,
                before=before,
                after=after,
                operation_count=len(operations),
            )
        )
    return PreparedTransaction(tuple(prepared))


def _stage_file(item: PreparedFile) -> tuple[Path, Path]:
    mode = stat.S_IMODE(item.path.stat().st_mode)
    staged = None
    backup = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=item.path.parent,
            prefix=".{}-content-stage-".format(item.path.name),
            suffix=".tmp",
            delete=False,
        ) as destination:
            staged = Path(destination.name)
            destination.write(item.after)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(staged, mode)
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=item.path.parent,
            prefix=".{}-content-backup-".format(item.path.name),
            suffix=".tmp",
            delete=False,
        ) as destination:
            backup = Path(destination.name)
            destination.write(item.before)
            destination.flush()
            os.fsync(destination.fileno())
        os.chmod(backup, mode)
        return staged, backup
    except BaseException:
        if staged is not None:
            staged.unlink(missing_ok=True)
        if backup is not None:
            backup.unlink(missing_ok=True)
        raise


def _sync_directories(directories: Sequence[Path]) -> None:
    """Persist rename metadata where the platform exposes directory fsync."""

    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    for directory in sorted(set(directories)):
        descriptor = os.open(directory, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def publish_transaction(
    root: Path,
    prepared: PreparedTransaction,
    *,
    failure_after: Optional[int] = None,
) -> None:
    """Publish all staged files, rolling back every replacement on failure."""

    root = root.resolve(strict=True)
    _verify_source_root(root)
    staged: dict[str, tuple[Path, Path]] = {}
    replaced: list[PreparedFile] = []
    changed_files = [item for item in prepared.files if item.before != item.after]
    try:
        for item in prepared.files:
            current = _safe_target(root, item.relative, item.format_name)
            if current != item.path or result_digest(current.read_bytes()) != result_digest(
                item.before
            ):
                raise ContentConflictError(
                    "{} changed after transaction preparation".format(item.relative),
                    code="concurrent-file-change",
                )
        for item in changed_files:
            staged[item.relative] = _stage_file(item)

        for index, item in enumerate(changed_files):
            current = _safe_target(root, item.relative, item.format_name)
            if result_digest(current.read_bytes()) != result_digest(item.before):
                raise ContentConflictError(
                    "{} changed immediately before publication".format(
                        item.relative
                    ),
                    code="concurrent-file-change",
                )
            if failure_after is not None and index == failure_after:
                raise OSError("injected transaction publication failure")
            stage, _ = staged[item.relative]
            replaced.append(item)
            os.replace(stage, item.path)
        _sync_directories([item.path.parent for item in changed_files])
    except BaseException as error:
        rollback_failures = []
        for item in reversed(replaced):
            _, backup = staged[item.relative]
            try:
                os.replace(backup, item.path)
            except OSError as rollback_error:
                rollback_failures.append(
                    "{}: {}".format(item.relative, rollback_error)
                )
        if replaced and not rollback_failures:
            try:
                _sync_directories([item.path.parent for item in replaced])
            except OSError as rollback_error:
                rollback_failures.append(
                    "directory synchronization: {}".format(rollback_error)
                )
        if rollback_failures:
            raise ContentCoreError(
                "transaction failed and rollback was incomplete: {}".format(
                    "; ".join(rollback_failures)
                ),
                kind="io",
                code="transaction-rollback-failed",
            ) from error
        if isinstance(error, ContentCoreError):
            raise
        raise ContentCoreError(
            "transaction publication failed; every replacement was rolled back: {}".format(
                error
            ),
            kind="io",
            code="transaction-publish-failed",
            retryable=True,
        ) from error
    finally:
        for stage, backup in staged.values():
            stage.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)


def apply_transaction(
    root: Path,
    transaction: object,
    *,
    apply: bool = False,
    schema_root: Path = PACKAGE_ROOT,
    failure_after: Optional[int] = None,
) -> Mapping[str, Any]:
    """Prepare a dry run by default, or atomically publish after full review."""

    prepared = prepare_transaction(root, transaction, schema_root=schema_root)
    if apply:
        publish_transaction(root, prepared, failure_after=failure_after)
    return prepared.result(dry_run=not apply, applied=apply)
