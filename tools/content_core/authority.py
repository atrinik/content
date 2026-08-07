"""One generated field-metadata adapter shared by parsing and serialization."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from tools.content_contracts.contracts import ContractError, confined_file, load_json

from .errors import ContentCoreError


@dataclass(frozen=True)
class FieldAuthority:
    """Validated lookup projections over the generated field metadata."""

    by_id: Mapping[str, Mapping[str, Any]]
    by_legacy: Mapping[tuple[str, str], Mapping[str, Any]]
    legacy_extensions: Mapping[str, Mapping[str, Any]]


def load_field_authority(root: Path) -> FieldAuthority:
    """Load one immutable authority adapter per canonical schema root."""

    return _load_field_authority(root.resolve(strict=True))


@lru_cache(maxsize=8)
def _load_field_authority(root: Path) -> FieldAuthority:
    try:
        path = confined_file(
            root,
            "schemas/authored-content-v1/field-metadata.json",
            "content field metadata",
        )
        metadata = load_json(path)
        source_path = confined_file(
            root,
            "schemas/authored-content-v1/source.json",
            "content field schema source",
        )
    except ContractError as error:
        raise ContentCoreError(
            str(error), code="invalid-field-metadata"
        ) from error
    if (
        not isinstance(metadata, dict)
        or set(metadata)
        != {
            "fields",
            "legacy_extensions",
            "limits",
            "logical_model",
            "registered_features",
            "schema_id",
            "schema_version",
            "source_sha256",
        }
        or metadata.get("schema_version") != 1
        or metadata.get("schema_id") != "atrinik-authored-content-v1"
        or not isinstance(metadata.get("fields"), list)
        or not isinstance(metadata.get("legacy_extensions"), dict)
    ):
        raise ContentCoreError(
            "content field metadata has an unsupported shape or version",
            code="invalid-field-metadata",
        )
    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if metadata.get("source_sha256") != source_digest:
        raise ContentCoreError(
            "content field metadata is stale for its authoritative source",
            code="stale-field-metadata",
        )

    by_id = {}
    by_legacy = {}
    required_field_keys = {
        "constraints",
        "context",
        "field_id",
        "legacy_name",
        "reference_domains",
        "roles",
        "status",
        "value_kind",
    }
    optional_field_keys = {"enum_values", "feature"}
    try:
        for field in metadata["fields"]:
            if (
                not isinstance(field, dict)
                or not required_field_keys <= set(field)
                or set(field) - required_field_keys - optional_field_keys
            ):
                raise ValueError("field entry has an unsupported shape")
            field_id = field["field_id"]
            context = field["context"]
            legacy_name = field["legacy_name"]
            if (
                not isinstance(field_id, str)
                or not isinstance(context, str)
                or not isinstance(field["constraints"], dict)
                or not isinstance(field["status"], str)
                or not isinstance(field["value_kind"], str)
            ):
                raise TypeError
            if legacy_name is not None and not isinstance(legacy_name, str):
                raise TypeError
            if field_id in by_id:
                raise ValueError("duplicate field ID {}".format(field_id))
            by_id[field_id] = field
            if legacy_name is not None:
                key = (context, legacy_name.casefold())
                if key in by_legacy:
                    raise ValueError(
                        "duplicate legacy field {}.{}".format(*key)
                    )
                by_legacy[key] = field
        extensions = metadata["legacy_extensions"]
        if any(
            not isinstance(name, str)
            or not isinstance(value, dict)
            or not {"custom_id", "owner", "status", "value_kind"} <= set(value)
            for name, value in extensions.items()
        ):
            raise TypeError
    except (KeyError, TypeError, ValueError) as error:
        raise ContentCoreError(
            "content field metadata is malformed: {}".format(error),
            code="invalid-field-metadata",
        ) from error

    return FieldAuthority(
        by_id=MappingProxyType(by_id),
        by_legacy=MappingProxyType(by_legacy),
        legacy_extensions=MappingProxyType(extensions),
    )
