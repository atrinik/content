"""Authoritative Atrinik authored-content schema and generated metadata."""

from .audit import audit_corpus
from .generate import check_outputs, render_outputs, write_outputs
from .logical import (
    dump_logical_document,
    load_logical_document,
    load_logical_schema,
    validate_logical_document,
)
from .model import SchemaError, field_definitions, load_schema_source

__all__ = (
    "SchemaError",
    "audit_corpus",
    "check_outputs",
    "dump_logical_document",
    "field_definitions",
    "load_logical_document",
    "load_schema_source",
    "load_logical_schema",
    "render_outputs",
    "write_outputs",
    "validate_logical_document",
)
