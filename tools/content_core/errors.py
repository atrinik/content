"""Stable failures for the lossless authored-content core."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


class ContentCoreError(ValueError):
    """A machine-readable content operation failure."""

    def __init__(
        self,
        message: str,
        *,
        kind: str = "schema",
        code: str = "content-core-error",
        retryable: bool = False,
        diagnostics: Sequence[Mapping[str, Any]] = (),
    ):
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.retryable = retryable
        self.diagnostics = tuple(diagnostics)

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "schema_version": 1,
            "kind": self.kind,
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "diagnostics": list(self.diagnostics),
        }


class ContentConflictError(ContentCoreError):
    """A digest, handle, fingerprint, or concurrent-write conflict."""

    def __init__(self, message: str, *, code: str = "content-conflict"):
        super().__init__(
            message,
            kind="conflict",
            code=code,
            retryable=True,
        )


class ContentSafetyError(ContentCoreError):
    """A write or path was outside the authored-content safety boundary."""

    def __init__(self, message: str, *, code: str = "unsafe-content-target"):
        super().__init__(message, kind="safety", code=code)


class ContentSyntaxError(ContentCoreError):
    """An authored document could not be safely decoded or parsed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid-content-document",
        diagnostics: Sequence[Mapping[str, Any]] = (),
    ):
        super().__init__(
            message,
            kind="syntax",
            code=code,
            diagnostics=diagnostics,
        )
