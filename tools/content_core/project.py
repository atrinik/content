"""Repository-aware document cache and stable content catalog lookup."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from tools.content_catalog import ContentCatalog, load_catalog
from tools.content_contracts.contracts import (
    ContractError,
    confined_file,
    safe_relative_path,
)

from .errors import ContentCoreError, ContentSafetyError
from .model import Document
from .parser import LegacyParser, PACKAGE_ROOT, parse_bytes


def audit_project(
    root: Path, *, schema_root: Path = PACKAGE_ROOT
) -> Mapping[str, Any]:
    """Parse every discoverable legacy source without retaining the full corpus."""

    root = root.resolve(strict=True)
    parser = LegacyParser(schema_root.resolve(strict=True))
    arch_root = root / "arch"
    maps_root = root / "maps"
    if not arch_root.is_dir() or not maps_root.is_dir():
        raise ContentSafetyError(
            "project audit requires authored arch/ and maps/ source roots",
            code="missing-authored-source-root",
        )

    archetypes = sorted(arch_root.rglob("*.arc"))
    maps = []
    for path in sorted(maps_root.rglob("*")):
        if path.is_symlink():
            raise ContentSafetyError(
                "project audit refuses symbolic links: {}".format(
                    path.relative_to(root).as_posix()
                )
            )
        if not path.is_file():
            continue
        with path.open("rb") as source:
            if source.read(9) == b"arch map\n":
                maps.append(path)

    invalid_files = []
    diagnostics: Counter[str] = Counter()
    for format_name, paths in (("archetype", archetypes), ("map", maps)):
        for path in paths:
            if path.is_symlink():
                raise ContentSafetyError(
                    "project audit refuses symbolic links: {}".format(
                        path.relative_to(root).as_posix()
                    )
                )
            relative = path.relative_to(root).as_posix()
            document = parser.parse(
                path.read_bytes(), path=relative, format_name=format_name
            )
            diagnostics.update(item["code"] for item in document.diagnostics)
            errors = sorted(
                item["code"]
                for item in document.diagnostics
                if item["severity"] == "error"
            )
            if errors:
                invalid_files.append({"path": relative, "codes": errors})
    return {
        "documents": len(archetypes) + len(maps),
        "archetypes": len(archetypes),
        "maps": len(maps),
        "diagnostics": dict(sorted(diagnostics.items())),
        "invalid_files": invalid_files,
    }


class ProjectIndex:
    """Lazy project index with explicit invalidation after filesystem changes."""

    def __init__(self, root: Path, *, schema_root: Path = PACKAGE_ROOT):
        self.root = root.resolve(strict=True)
        self.schema_root = schema_root.resolve(strict=True)
        self._documents: Dict[str, tuple[tuple[object, ...], Document]] = {}
        self._catalog: Optional[ContentCatalog] = None

    def document(self, relative: str, *, format_name: Optional[str] = None) -> Document:
        try:
            relative = safe_relative_path(relative, "project document path")
            path = confined_file(self.root, relative, "project document")
        except ContractError as error:
            raise ContentSafetyError(str(error)) from error
        detected = format_name or self._format(relative, path)
        stat = path.stat()
        key = (
            stat.st_dev,
            stat.st_ino,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
            stat.st_size,
            detected,
        )
        cached = self._documents.get(relative)
        if cached is not None and cached[0] == key:
            return cached[1]
        document = parse_bytes(
            path.read_bytes(),
            path=relative,
            format_name=detected,
            schema_root=self.schema_root,
        )
        self._documents[relative] = (key, document)
        return document

    def invalidate(self, paths: Sequence[str] = ()) -> None:
        """Invalidate selected documents and the derived catalog."""

        if paths:
            for path in paths:
                try:
                    relative = safe_relative_path(path, "invalidated project path")
                except ContractError as error:
                    raise ContentSafetyError(str(error)) from error
                self._documents.pop(relative, None)
        else:
            self._documents.clear()
        self._catalog = None

    def catalog(self) -> ContentCatalog:
        if self._catalog is None:
            self._catalog = load_catalog(self.root)
        return self._catalog

    def search(
        self,
        *,
        kind: Optional[str],
        text: str,
        limit: int = 50,
    ) -> Mapping[str, Any]:
        if (
            not isinstance(text, str)
            or text != text.strip()
            or len(text.encode("utf-8")) > 256
        ):
            raise ContentCoreError(
                "catalog search text must be trimmed and at most 256 UTF-8 bytes",
                code="invalid-catalog-query",
            )
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ContentCoreError(
                "catalog search limit must be 1..100",
                code="invalid-catalog-limit",
            )
        if kind is not None and (
            not isinstance(kind, str) or not kind or kind != kind.strip()
        ):
            raise ContentCoreError(
                "catalog kind must be non-empty trimmed text",
                code="invalid-catalog-kind",
            )
        needle = text.casefold()
        matches = []
        for definition in self.catalog().definitions:
            if kind is not None and definition.content_id.domain != kind:
                continue
            searchable = "{} {} {}".format(
                definition.content_id.domain,
                definition.content_id.key,
                " ".join(str(value) for value in definition.metadata.values()),
            ).casefold()
            if needle not in searchable:
                continue
            matches.append(
                {
                    "domain": definition.content_id.domain,
                    "key": definition.content_id.key,
                    "location": definition.location.to_dict(),
                    "metadata": dict(sorted(definition.metadata.items())),
                }
            )
        return {
            "schema_version": 1,
            "kind": "catalog-search",
            "query": {"kind": kind, "text": text, "limit": limit},
            "results": matches[:limit],
            "truncated": len(matches) > limit,
        }

    @staticmethod
    def _format(relative: str, path: Path) -> str:
        parts = Path(relative).parts
        if parts and parts[0] == "arch" and path.suffix == ".arc":
            return "archetype"
        if parts and parts[0] == "maps":
            return "map"
        raise ContentSafetyError(
            "project documents must be authored maps or arch/*.arc files",
            code="unsupported-project-document",
        )
