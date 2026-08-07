"""Deterministic evaluation against the locked content-v1 parity corpus."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.content_contracts.contracts import confined_file, load_json
from tools.content_contracts.corpus import inspect_document

from . import jsonc, yaml12
from .limits import PrototypeError
from .model import from_legacy, validate as validate_model


BASELINE_ROOT = Path("contracts/content-v1")
LOCK_PATH = Path("prototypes/authored-syntax-v1/baseline-lock.json")
CODECS = {"jsonc": jsonc, "yaml12": yaml12}


def _source_bytes(root: Path, fixture: dict[str, Any]) -> bytes:
    source = fixture["source"]
    if set(source) == {"path"}:
        path = confined_file(root / BASELINE_ROOT, source["path"], "syntax corpus source")
        return path.read_bytes()
    if set(source) == {"base64"}:
        try:
            return base64.b64decode(source["base64"], validate=True)
        except (ValueError, binascii.Error) as error:
            raise PrototypeError("invalid inline corpus source") from error
    raise PrototypeError("corpus fixture source is not closed")


def _logical_id(fixture: dict[str, Any]) -> str:
    if fixture["format"] == "map":
        return "/contracts/content-v1/" + fixture["id"]
    return "archetype:contracts/content-v1/" + fixture["id"]


def _baseline_files(root: Path) -> list[Path]:
    baseline = root / BASELINE_ROOT
    paths = [
        baseline / "grammar-inventory.json",
        baseline / "consumer-inventory.json",
        baseline / "corpus/manifest.json",
    ]
    manifest = load_json(baseline / "corpus/manifest.json")
    for fixture in manifest["fixtures"]:
        source = fixture["source"]
        if "path" in source:
            paths.append(confined_file(baseline, source["path"], "baseline lock source"))
    return sorted(set(paths), key=lambda path: path.relative_to(root).as_posix())


def baseline_snapshot(root: Path) -> dict[str, Any]:
    files = []
    aggregate = hashlib.sha256()
    for path in _baseline_files(root):
        raw = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(raw).hexdigest()
        files.append({"path": relative, "bytes": len(raw), "sha256": digest})
        aggregate.update(relative.encode("utf-8") + b"\0" + raw + b"\0")
    return {"schema_version": 1, "sha256": aggregate.hexdigest(), "files": files}


def validate_baseline_lock(root: Path) -> dict[str, Any]:
    expected = load_json(root / LOCK_PATH)
    actual = baseline_snapshot(root)
    if actual != expected:
        raise PrototypeError(
            "content-v1 baseline differs from the explicit authored-syntax lock; "
            "correct #17 first or record the reviewed correction"
        )
    return actual


def evaluate_corpus(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    lock = validate_baseline_lock(root)
    baseline = root / BASELINE_ROOT
    manifest = load_json(baseline / "corpus/manifest.json")
    grammar = load_json(baseline / "grammar-inventory.json")
    reports = []

    for fixture in manifest["fixtures"]:
        raw = _source_bytes(root, fixture)
        display = "contracts/content-v1/" + fixture["id"]
        inspection, summary = inspect_document(
            baseline,
            fixture["format"],
            grammar,
            display_path=display,
            source_bytes=raw,
        )
        if summary != fixture["expected"]:
            raise PrototypeError("fixed baseline summary changed for {}".format(fixture["id"]))
        model = from_legacy(
            raw,
            fixture["format"],
            _logical_id(fixture),
            inspection["comments"],
        )
        formats = {}
        for name, codec in CODECS.items():
            encoded = codec.encode(model)
            decoded = codec.decode(encoded)
            reconstructed = validate_model(decoded)
            if decoded != model or reconstructed != raw:
                raise PrototypeError("{} prototype lost bytes for {}".format(name, fixture["id"]))
            if codec.encode(decoded) != encoded:
                raise PrototypeError(
                    "{} prototype is not deterministic for {}".format(
                        name, fixture["id"]
                    )
                )
            _, after = inspect_document(
                baseline,
                fixture["format"],
                grammar,
                display_path=display,
                source_bytes=reconstructed,
            )
            if after != summary:
                raise PrototypeError(
                    "{} prototype lost semantics for {}".format(name, fixture["id"])
                )
            encoded_bytes = encoded.encode("utf-8")
            formats[name] = {
                "bytes": len(encoded_bytes),
                "sha256": hashlib.sha256(encoded_bytes).hexdigest(),
                "expansion_ratio": round(len(encoded_bytes) / len(raw), 6),
            }
        reports.append(
            {
                "id": fixture["id"],
                "format": fixture["format"],
                "accepted_by_contract": summary["accepted"],
                "legacy_bytes": len(raw),
                "legacy_sha256": hashlib.sha256(raw).hexdigest(),
                "formats": formats,
            }
        )

    return {
        "schema_version": 1,
        "baseline_sha256": lock["sha256"],
        "fixtures": reports,
        "summary": {
            "fixtures": len(reports),
            "malformed_fixtures": sum(not report["accepted_by_contract"] for report in reports),
            "formats": sorted(CODECS),
            "byte_exact_roundtrips": len(reports) * len(CODECS),
            "semantic_roundtrips": len(reports) * len(CODECS),
        },
    }
