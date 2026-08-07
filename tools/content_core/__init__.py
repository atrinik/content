"""Lossless authored-content core and safe project operations."""

from .errors import (
    ContentConflictError,
    ContentCoreError,
    ContentSafetyError,
    ContentSyntaxError,
)
from .model import Document, FieldRecord, Node, SourceSpan
from .operations import FieldRegistry, result_digest, semantic_comparison
from .parser import LegacyParser, parse_bytes, parse_file
from .project import ProjectIndex, audit_project
from .transaction import apply_transaction, prepare_transaction, publish_transaction

__all__ = (
    "ContentConflictError",
    "ContentCoreError",
    "ContentSafetyError",
    "ContentSyntaxError",
    "Document",
    "FieldRecord",
    "FieldRegistry",
    "LegacyParser",
    "Node",
    "ProjectIndex",
    "SourceSpan",
    "parse_bytes",
    "parse_file",
    "apply_transaction",
    "audit_project",
    "prepare_transaction",
    "publish_transaction",
    "result_digest",
    "semantic_comparison",
)
