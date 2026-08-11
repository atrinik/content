"""Load Atrinik's authored content into a typed identity graph."""

from __future__ import annotations

import ast
import os
import posixpath
import re
import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from xml.parsers import expat

from .model import ContentCatalog, ContentId, SourceLocation


QUEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
QUEST_PART_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
OBJECT_DOMAINS = ("archetype", "artifact")
CONTENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


def _load_content_identities(catalog: ContentCatalog, maps_root: Path) -> None:
    """Load explicit NPC and property identities owned by authored content."""

    path = maps_root / "content-identities.json"
    if not path.is_file():
        return
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        catalog.add_diagnostic(
            "invalid-content-identities", str(error), catalog.location(path, 1)
        )
        return
    if not isinstance(document, dict) or set(document) != {
        "schema_version", "npcs", "properties"
    } or document.get("schema_version") != 1:
        catalog.add_diagnostic(
            "invalid-content-identities",
            "content identity registry must be a closed schema-version 1 object",
            catalog.location(path, 1),
        )
        return
    for field, domain in (("npcs", "npc"), ("properties", "property")):
        entries = document[field]
        if not isinstance(entries, list):
            catalog.add_diagnostic(
                "invalid-content-identities",
                "{} must be an array".format(field),
                catalog.location(path, 1),
            )
            continue
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {"id"}:
                catalog.add_diagnostic(
                    "invalid-content-identity",
                    "{} entries must contain only id".format(field),
                    catalog.location(path, 1),
                )
                continue
            key = entry.get("id")
            if not isinstance(key, str) or not CONTENT_ID_RE.fullmatch(key):
                catalog.add_diagnostic(
                    "invalid-content-identity",
                    "{} id must be a portable stable identifier".format(domain),
                    catalog.location(path, 1),
                )
                continue
            catalog.add_definition(domain, key, catalog.location(path, 1))


def _validate_source_roots(
    catalog: ContentCatalog, roots: Sequence[Path]
) -> bool:
    """Reject absent source roots and filesystem indirection before parsing."""

    valid = True
    for root in roots:
        if root.is_symlink() or not root.is_dir():
            code = "unsafe-source-link" if root.is_symlink() else "missing-source-root"
            message = (
                "authored source root must not be a symbolic link"
                if root.is_symlink()
                else "required authored source root is missing"
            )
            catalog.add_diagnostic(code, message, catalog.location(root, 1))
            valid = False
            continue

        def handle_walk_error(error: OSError) -> None:
            nonlocal valid
            catalog.add_diagnostic(
                "source-io-error",
                str(error),
                catalog.location(Path(error.filename or root), 1),
            )
            valid = False

        for directory, dirnames, filenames in os.walk(
            root, followlinks=False, onerror=handle_walk_error
        ):
            dirnames.sort()
            filenames.sort()
            directory_path = Path(directory)
            for name in tuple(dirnames):
                path = directory_path / name
                if path.is_symlink():
                    catalog.add_diagnostic(
                        "unsafe-source-link",
                        "symbolic links are not allowed in authored sources",
                        catalog.location(path, 1),
                    )
                    dirnames.remove(name)
                    valid = False
            for name in filenames:
                path = directory_path / name
                if path.is_symlink():
                    catalog.add_diagnostic(
                        "unsafe-source-link",
                        "symbolic links are not allowed in authored sources",
                        catalog.location(path, 1),
                    )
                    valid = False
                elif not path.is_file():
                    catalog.add_diagnostic(
                        "unsafe-source-file",
                        "authored sources must be regular files",
                        catalog.location(path, 1),
                    )
                    valid = False
    return valid


def _iter_source_lines(
    path: Path, catalog: ContentCatalog
) -> Iterator[Tuple[int, str]]:
    """Yield significant lines while respecting classic msg/endmsg blocks."""

    in_message = False
    message_line = 0
    with path.open(encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, 1):
            raw_line = raw_line.rstrip("\r\n")
            line = raw_line.strip()
            if in_message:
                if line == "endmsg":
                    in_message = False
                continue
            if line == "msg":
                in_message = True
                message_line = line_number
                continue
            if not line or line.startswith("#"):
                continue
            yield line_number, raw_line
    if in_message:
        catalog.add_diagnostic(
            "unterminated-message",
            "msg block has no endmsg",
            catalog.location(path, message_line),
        )


def _split(line: str) -> Tuple[str, str]:
    parts = line.split(None, 1)
    return parts[0], parts[1].strip() if len(parts) == 2 else ""


def _column(line: str, value: str) -> int:
    position = line.find(value)
    return position + 1 if position >= 0 else 1


def _load_archetypes(catalog: ContentCatalog, arch_root: Path) -> None:
    for path in sorted(arch_root.rglob("*.arc")):
        current: Optional[ContentId] = None
        current_type: Optional[str] = None
        current_location: Optional[SourceLocation] = None
        multipart_continuation = False
        inside_object = False

        for line_number, line in _iter_source_lines(path, catalog):
            field, value = _split(line)
            if field == "More" and not value:
                multipart_continuation = True
                continue
            if field == "Object" and value:
                if inside_object:
                    catalog.add_diagnostic(
                        "unterminated-object",
                        "Object block has no end before the next Object",
                        current_location or catalog.location(path, line_number),
                    )
                inside_object = True
                current_type = None
                current_location = catalog.location(path, line_number, _column(line, value))
                if multipart_continuation:
                    current = None
                else:
                    current = catalog.add_definition(
                        "archetype", value, current_location
                    )
                multipart_continuation = False
                continue
            if not inside_object:
                continue
            if field == "type" and value:
                current_type = value.split()[0]
            elif field == "other_arch" and value:
                catalog.add_reference(
                    value.split()[0],
                    ("archetype",),
                    catalog.location(path, line_number, _column(line, value)),
                    "other_arch",
                    current,
                )
            elif field == "randomitems" and value:
                catalog.add_reference(
                    value.split()[0],
                    ("treasure",),
                    catalog.location(path, line_number, _column(line, value)),
                    "randomitems",
                    current,
                )
            elif field == "end" and not value:
                if current is not None and current_type in ("29", "43"):
                    domain = "spell" if current_type == "29" else "skill"
                    catalog.add_definition(
                        domain,
                        current.key,
                        current_location or catalog.location(path, line_number),
                        {"archetype": current.key},
                    )
                inside_object = False
                current = None
                current_type = None
        if inside_object:
            catalog.add_diagnostic(
                "unterminated-object",
                "Object block has no end",
                current_location or catalog.location(path, 1),
            )
        elif multipart_continuation:
            catalog.add_diagnostic(
                "dangling-multipart",
                "More is not followed by an Object block",
                catalog.location(path, 1),
            )


def _load_runtime_identity_tables(catalog: ContentCatalog, server_root: Path) -> None:
    """Validate explicit stable IDs used by process-local C lookup tables."""

    definitions = tuple(catalog.definitions)
    definition_ids = {definition.content_id for definition in definitions}
    table_specs = (
        (server_root / "src/include/spellist.h", "spell", "spell table id"),
        (server_root / "src/include/skillist.h", "skill", "skill table id"),
    )
    for path, domain, field in table_specs:
        if not path.is_file():
            continue
        if path.is_symlink() or catalog.root not in path.resolve().parents:
            catalog.add_diagnostic(
                "unsafe-source-link",
                "runtime identity table resolves outside the source root",
                catalog.location(path, 1),
            )
            continue
        seen: Dict[str, SourceLocation] = {}
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                for match in re.finditer(r'\{"((?:spell|skill)_[a-z0-9_]+)"\s*,', line):
                    key = match.group(1)
                    location = catalog.location(path, line_number, match.start(1) + 1)
                    previous = seen.get(key)
                    if previous is not None:
                        catalog.add_diagnostic(
                            "duplicate-runtime-id",
                            "duplicate {} {}; first declared at {}".format(
                                domain, key, previous.display()
                            ),
                            location,
                            related=previous,
                        )
                        continue
                    seen[key] = location
                    # Some reserved skill enum slots do not have an obtainable
                    # skill archetype. Existing authored skills must map to
                    # stable table IDs; unused slots remain process-local.
                    if domain == "spell" or ContentId(domain, key) in definition_ids:
                        catalog.add_reference(key, (domain,), location, field)

        table_ids = set(seen)
        for definition in definitions:
            if definition.content_id.domain != domain:
                continue
            if definition.content_id.key not in table_ids:
                catalog.add_diagnostic(
                    "missing-runtime-id",
                    "{} {} has no stable entry in {}".format(
                        domain, definition.content_id.key, path.name
                    ),
                    definition.location,
                )


def _load_artifacts(catalog: ContentCatalog, roots: Sequence[Path]) -> None:
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.art")):
            current: Optional[ContentId] = None
            current_location: Optional[SourceLocation] = None
            for line_number, line in _iter_source_lines(path, catalog):
                field, value = _split(line)
                if field == "artifact" and value:
                    location = catalog.location(path, line_number, _column(line, value))
                    if current is not None:
                        catalog.add_diagnostic(
                            "unterminated-artifact",
                            "artifact block has no end before the next artifact",
                            current_location or location,
                        )
                    current = catalog.add_definition("artifact", value, location)
                    current_location = location
                elif field == "def_arch" and value:
                    catalog.add_reference(
                        value.split()[0],
                        OBJECT_DOMAINS,
                        catalog.location(path, line_number, _column(line, value)),
                        "def_arch",
                        current,
                    )
                elif field == "spell_id" and value:
                    catalog.add_reference(
                        value,
                        ("spell",),
                        catalog.location(path, line_number, _column(line, value)),
                        "spell_id",
                        current,
                    )
                elif field == "skill_id" and value:
                    catalog.add_reference(
                        value,
                        ("skill",),
                        catalog.location(path, line_number, _column(line, value)),
                        "skill_id",
                        current,
                    )
                elif field == "end" and not value:
                    current = None
                    current_location = None
            if current is not None:
                catalog.add_diagnostic(
                    "unterminated-artifact",
                    "artifact block has no end",
                    current_location or catalog.location(path, line_number),
                )


def _load_treasures(catalog: ContentCatalog, roots: Sequence[Path]) -> None:
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.trs")):
            current: Optional[ContentId] = None
            current_location: Optional[SourceLocation] = None
            for line_number, line in _iter_source_lines(path, catalog):
                field, value = _split(line)
                if field in ("treasure", "treasureone") and value:
                    location = catalog.location(path, line_number, _column(line, value))
                    if current is not None:
                        catalog.add_diagnostic(
                            "unterminated-treasure",
                            "treasure block has no end before the next treasure",
                            current_location or location,
                        )
                    current = catalog.add_definition("treasure", value, location)
                    current_location = location
                elif field == "arch" and value:
                    catalog.add_reference(
                        value.split()[0],
                        OBJECT_DOMAINS,
                        catalog.location(path, line_number, _column(line, value)),
                        "treasure arch",
                        current,
                    )
                elif field == "list" and value and value != "NONE":
                    catalog.add_reference(
                        value.split()[0],
                        ("treasure",),
                        catalog.location(path, line_number, _column(line, value)),
                        "treasure list",
                        current,
                    )
                elif field == "end" and not value:
                    current = None
                    current_location = None
            if current is not None:
                catalog.add_diagnostic(
                    "unterminated-treasure",
                    "treasure block has no end",
                    current_location or catalog.location(path, line_number),
                )


def _load_factions(catalog: ContentCatalog, maps_root: Path) -> None:
    parents: Dict[str, Tuple[str, SourceLocation]] = {}
    for path in sorted(maps_root.rglob("*.factions")):
        stack: List[ContentId] = []
        for line_number, line in _iter_source_lines(path, catalog):
            field, value = _split(line)
            if field == "faction" and value:
                location = catalog.location(path, line_number, _column(line, value))
                content_id = catalog.add_definition("faction", value, location)
                if stack:
                    parent = stack[-1]
                    catalog.add_reference(
                        parent.key, ("faction",), location, "nested faction parent", content_id
                    )
                    parents[content_id.key] = (parent.key, location)
                stack.append(content_id)
            elif field == "parent" and value and stack:
                location = catalog.location(path, line_number, _column(line, value))
                catalog.add_reference(value, ("faction",), location, "faction parent", stack[-1])
                parents[stack[-1].key] = (value, location)
            elif field == "enemy" and value:
                catalog.add_reference(
                    value,
                    ("faction",),
                    catalog.location(path, line_number, _column(line, value)),
                    "faction enemy",
                    stack[-1] if stack else None,
                )
            elif field == "end" and not value and stack:
                stack.pop()
        if stack:
            catalog.add_diagnostic(
                "unterminated-faction",
                "faction block has no end",
                catalog.location(path, line_number),
            )
    catalog.check_cycles("faction", parents)


def _load_regions(catalog: ContentCatalog, maps_root: Path) -> None:
    path = maps_root / "regions.reg"
    if not path.is_file():
        return
    current: Optional[ContentId] = None
    current_location: Optional[SourceLocation] = None
    parents: Dict[str, Tuple[str, SourceLocation]] = {}
    for line_number, line in _iter_source_lines(path, catalog):
        field, value = _split(line)
        if field == "region" and value:
            location = catalog.location(path, line_number, _column(line, value))
            if current is not None:
                catalog.add_diagnostic(
                    "unterminated-region",
                    "region block has no end before the next region",
                    current_location or location,
                )
            current = catalog.add_definition("region", value, location)
            current_location = location
        elif field == "parent" and value and current is not None:
            location = catalog.location(path, line_number, _column(line, value))
            catalog.add_reference(value, ("region",), location, "region parent", current)
            parents[current.key] = (value, location)
        elif field in ("map_first", "jail") and value:
            map_key = value.split()[0]
            _add_map_reference(
                catalog,
                map_key,
                catalog.location(path, line_number, _column(line, map_key)),
                "region {}".format(field),
                current,
            )
        elif field == "end" and not value:
            current = None
            current_location = None
    if current is not None:
        catalog.add_diagnostic(
            "unterminated-region",
            "region block has no end",
            current_location or catalog.location(path, line_number),
        )
    catalog.check_cycles("region", parents)


def _canonical_map_path(path: str, base: Optional[str] = None) -> str:
    combined = path.lstrip("/") if path.startswith("/") else posixpath.join(
        (base or "/").lstrip("/"), path
    )
    parts: List[str] = []
    for part in combined.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ValueError("map path escapes the maps root")
            parts.pop()
        else:
            parts.append(part)
    return "/" + "/".join(parts)


def _add_map_reference(
    catalog: ContentCatalog,
    path: str,
    location: SourceLocation,
    field: str,
    source: Optional[ContentId],
    base: Optional[str] = None,
) -> None:
    try:
        key = _canonical_map_path(path, base)
    except ValueError as error:
        catalog.add_diagnostic("invalid-map-path", "{}: {}".format(field, error), location)
        return
    catalog.add_reference(key, ("map",), location, field, source)


def _is_map_file(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as source:
            for raw_line in source:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                return line == "arch map"
    except (OSError, UnicodeDecodeError):
        return False
    return False


def _load_maps(catalog: ContentCatalog, maps_root: Path) -> None:
    ignored_suffixes = {
        ".art",
        ".dtd",
        ".factions",
        ".md",
        ".png",
        ".py",
        ".pyc",
        ".reg",
        ".rst",
        ".trs",
        ".txt",
        ".xml",
    }
    for path in sorted(item for item in maps_root.rglob("*") if item.is_file()):
        if path.suffix.lower() in ignored_suffixes or not _is_map_file(path):
            continue
        map_key = "/" + path.relative_to(maps_root).as_posix()
        map_id = catalog.add_definition("map", map_key, catalog.location(path, 1))
        in_header = True
        # A map may place thousands of identical objects. One edge per target
        # preserves identity validation without turning the catalog artifact
        # into a second, much larger encoding of the map itself.
        seen_archetypes = set()
        for line_number, line in _iter_source_lines(path, catalog):
            field, value = _split(line)
            if in_header:
                if field == "region" and value:
                    catalog.add_reference(
                        value,
                        ("region",),
                        catalog.location(path, line_number, _column(line, value)),
                        "map region",
                        map_id,
                    )
                elif field.startswith("tile_path_") and value:
                    _add_map_reference(
                        catalog,
                        value,
                        catalog.location(path, line_number, _column(line, value)),
                        field,
                        map_id,
                        posixpath.dirname(map_key),
                    )
                elif field == "end" and not value:
                    in_header = False
            elif field == "arch" and value:
                target = value.split()[0]
                if target in seen_archetypes:
                    continue
                seen_archetypes.add(target)
                catalog.add_reference(
                    target,
                    OBJECT_DOMAINS,
                    catalog.location(path, line_number, _column(line, value)),
                    "map arch",
                    map_id,
                )
            elif field == "spell_id" and value:
                catalog.add_reference(
                    value,
                    ("spell",),
                    catalog.location(path, line_number, _column(line, value)),
                    "spell_id",
                    map_id,
                )
            elif field == "skill_id" and value:
                catalog.add_reference(
                    value,
                    ("skill",),
                    catalog.location(path, line_number, _column(line, value)),
                    "skill_id",
                    map_id,
                )
            elif field in ("npc_id", "property_id") and value:
                catalog.add_reference(
                    value,
                    ("npc" if field == "npc_id" else "property",),
                    catalog.location(path, line_number, _column(line, value)),
                    field,
                    map_id,
                )
        if in_header:
            catalog.add_diagnostic(
                "unterminated-map-header",
                "map header has no end",
                catalog.location(path, 1),
            )


class _InterfaceLoader:
    QUEST_FIELDS = ("start", "complete", "fail", "started", "finished", "completed", "failed")

    def __init__(self, catalog: ContentCatalog, path: Path, quest_key: Optional[str]):
        self.catalog = catalog
        self.path = path
        self.quest_key = quest_key
        self.quest_id: Optional[ContentId] = None
        self.part_stack: List[str] = []
        self.contents = path.read_bytes()
        self.parser = expat.ParserCreate()
        self.parser.StartElementHandler = self._start
        self.parser.EndElementHandler = self._end

    def location(self, attribute_value: Optional[str] = None) -> SourceLocation:
        line = self.parser.CurrentLineNumber
        column = self.parser.CurrentColumnNumber + 1
        if attribute_value:
            encoded_value = attribute_value.encode("utf-8")
            element_start = self.parser.CurrentByteIndex
            element_end = self.contents.find(b">", element_start)
            position = self.contents.find(
                encoded_value,
                element_start,
                element_end if element_end >= 0 else len(self.contents),
            )
            if position >= 0:
                line = self.contents.count(b"\n", 0, position) + 1
                previous_newline = self.contents.rfind(b"\n", 0, position)
                column = position - previous_newline
        return self.catalog.location(self.path, line, column)

    def parse(self) -> None:
        try:
            self.parser.Parse(self.contents, True)
        except expat.ExpatError as error:
            self.catalog.add_diagnostic(
                "invalid-xml",
                str(error),
                self.catalog.location(self.path, error.lineno, error.offset + 1),
            )

    def _start(self, name: str, attrs: Dict[str, str]) -> None:
        if name == "quest":
            if self.quest_key is None:
                self.catalog.add_diagnostic(
                    "quest-location",
                    "quest definitions must be stored below maps/interfaces/quests/<uid>/",
                    self.location(),
                )
            else:
                if not QUEST_ID_RE.fullmatch(self.quest_key):
                    self.catalog.add_diagnostic(
                        "invalid-quest-id",
                        "quest directory '{}' is not a stable identifier".format(self.quest_key),
                        self.location(),
                    )
                self.quest_id = self.catalog.add_definition(
                    "quest", self.quest_key, self.location(), {"name": attrs.get("name", "")}
                )
        elif name == "part":
            uid = attrs.get("uid", "")
            if not QUEST_PART_ID_RE.fullmatch(uid):
                self.catalog.add_diagnostic(
                    "invalid-quest-part-id",
                    "quest part uid '{}' must match {}".format(uid, QUEST_PART_ID_RE.pattern),
                    self.location(uid),
                )
            self.part_stack.append(uid)
            if self.quest_key is not None:
                key = self.quest_key + "::" + "::".join(self.part_stack)
                self.catalog.add_definition(
                    "quest-part", key, self.location(uid), {"uid": uid}
                )

        source = self.quest_id
        if name in ("item", "object") and attrs.get("arch"):
            self.catalog.add_reference(
                attrs["arch"],
                OBJECT_DOMAINS,
                self.location(attrs["arch"]),
                "{} arch".format(name),
                source,
            )
        if attrs.get("cast"):
            spell_key = "spell_" + re.sub(r"\s+", "_", attrs["cast"].strip().lower())
            self.catalog.add_reference(
                spell_key,
                ("spell",),
                self.location(attrs["cast"]),
                "cast",
                source,
            )
        if attrs.get("teleport"):
            target = attrs["teleport"].split()[0]
            _add_map_reference(
                self.catalog,
                target,
                self.location(target),
                "teleport",
                source,
            )
        if attrs.get("region_map"):
            self.catalog.add_reference(
                attrs["region_map"],
                ("region",),
                self.location(attrs["region_map"]),
                "region_map",
                source,
            )
        for attribute, domain in (("npc_id", "npc"), ("property_id", "property")):
            value = attrs.get(attribute)
            if value:
                self.catalog.add_reference(
                    value, (domain,), self.location(value), attribute, source
                )
        property_action = attrs.get("property_action_id")
        if property_action:
            self.catalog.add_reference(
                property_action, ("property-action",),
                self.location(property_action), "property_action_id", source
            )
        for attribute, value in attrs.items():
            if attribute.startswith("faction_"):
                self.catalog.add_reference(
                    value, ("faction",), self.location(value), attribute, source
                )
        if self.quest_key is not None:
            for field in self.QUEST_FIELDS:
                value = attrs.get(field)
                if value:
                    key = self.quest_key + "::" + value
                    self.catalog.add_reference(
                        key, ("quest-part",), self.location(value), field, source
                    )

    def _end(self, name: str) -> None:
        if name == "part" and self.part_stack:
            self.part_stack.pop()


def _load_interfaces(catalog: ContentCatalog, maps_root: Path) -> None:
    interfaces_root = maps_root / "interfaces"
    quests_root = interfaces_root / "quests"
    if not interfaces_root.is_dir():
        return
    for path in sorted(interfaces_root.rglob("*.xml")):
        quest_key = None
        try:
            relative = path.relative_to(quests_root)
            if len(relative.parts) >= 2:
                quest_key = relative.parts[0]
        except ValueError:
            pass
        _InterfaceLoader(catalog, path, quest_key).parse()


def _map_object_bindings(path: Path, catalog: ContentCatalog) -> List[dict]:
    """Return effective identity fields for nested objects in one map."""

    bindings: List[dict] = []
    stack: List[dict] = []
    for _line_number, line in _iter_source_lines(path, catalog):
        field, value = _split(line)
        if field == "arch" and value:
            parent = stack[-1] if stack else {}
            stack.append({
                "archetype": value.split()[0],
                "x": parent.get("x", 0),
                "y": parent.get("y", 0),
            })
        elif field == "end" and not value:
            if stack:
                bindings.append(stack.pop())
        elif stack and field in ("name", "x", "y"):
            stack[-1][field] = int(value) if field in ("x", "y") else value
    return bindings


def _classic_apartment_tags(root: Path, catalog: ContentCatalog) -> set[str]:
    """Read literal Classic apartment tags without importing runtime Python."""

    path = root / "maps" / "python" / "Apartments.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for statement in tree.body:
            if (isinstance(statement, ast.Assign) and
                    any(isinstance(target, ast.Name) and
                        target.id == "apartments_info" for target in statement.targets)):
                document = ast.literal_eval(statement.value)
                return {
                    value["tag"] for value in document.values()
                    if isinstance(value, dict) and isinstance(value.get("tag"), str)
                }
    except (OSError, UnicodeError, SyntaxError, ValueError) as error:
        catalog.add_diagnostic(
            "invalid-property-runtime-binding", str(error), catalog.location(path, 1)
        )
    return set()


def _load_property_interactions(catalog: ContentCatalog, maps_root: Path) -> None:
    """Load typed property actions and prove their authored/runtime bindings."""

    path = maps_root / "property-interactions.json"
    if not path.is_file():
        return
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        catalog.add_diagnostic(
            "invalid-property-interactions", str(error), catalog.location(path, 1)
        )
        return
    if (not isinstance(document, dict) or
            set(document) != {"schema_version", "interactions"} or
            document.get("schema_version") != 1 or
            not isinstance(document.get("interactions"), list)):
        catalog.add_diagnostic(
            "invalid-property-interactions",
            "property interactions must use the closed schema-version 1 shape",
            catalog.location(path, 1),
        )
        return

    tags = _classic_apartment_tags(catalog.root, catalog)
    entry_fields = {
        "id", "quest_id", "quest_part_id", "npc_id", "property_id",
        "npc_binding", "portal_binding", "grant", "completion", "runtime_owners",
    }
    binding_fields = {"map", "x", "y", "archetype", "name"}
    for entry in document["interactions"]:
        if not isinstance(entry, dict) or set(entry) != entry_fields:
            catalog.add_diagnostic(
                "invalid-property-interaction", "property interaction has unknown or missing fields",
                catalog.location(path, 1),
            )
            continue
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not CONTENT_ID_RE.fullmatch(identifier):
            catalog.add_diagnostic(
                "invalid-property-interaction", "interaction id must be stable",
                catalog.location(path, 1),
            )
            continue
        source = catalog.add_definition(
            "property-action", identifier, catalog.location(path, 1)
        )
        references = (
            (entry.get("quest_id"), "quest", "quest_id"),
            ("{}::{}".format(entry.get("quest_id"), entry.get("quest_part_id")),
             "quest-part", "quest_part_id"),
            (entry.get("npc_id"), "npc", "npc_id"),
            (entry.get("property_id"), "property", "property_id"),
        )
        for key, domain, field in references:
            if isinstance(key, str):
                catalog.add_reference(
                    key, (domain,), catalog.location(path, 1), field, source
                )

        for field, extra in (("npc_binding", set()),
                             ("portal_binding", {"return_x", "return_y"})):
            binding = entry.get(field)
            if not isinstance(binding, dict) or set(binding) != binding_fields | extra:
                catalog.add_diagnostic(
                    "invalid-property-binding", "{} has an invalid shape".format(field),
                    catalog.location(path, 1),
                )
                continue
            map_key = binding.get("map")
            if isinstance(map_key, str):
                _add_map_reference(
                    catalog, map_key, catalog.location(path, 1), field, source
                )
                try:
                    map_path = maps_root / _canonical_map_path(map_key).lstrip("/")
                    objects = _map_object_bindings(map_path, catalog)
                except (OSError, UnicodeError, ValueError):
                    objects = []
                if not any(
                    obj.get("archetype") == binding.get("archetype") and
                    obj.get("name") == binding.get("name") and
                    obj.get("x") == binding.get("x") and
                    obj.get("y") == binding.get("y")
                    for obj in objects
                ):
                    catalog.add_diagnostic(
                        "missing-property-binding",
                        "{} does not match an authored map object".format(field),
                        catalog.location(path, 1),
                    )

        grant = entry.get("grant")
        if not isinstance(grant, dict) or grant != {
            "operation": "ensure_ownership", "tier": "cheap", "price": 0,
            "emit_purchase_event": False, "preserve_existing_tier": True,
            "idempotency_scope": "character_property",
        }:
            catalog.add_diagnostic(
                "invalid-property-grant", "tutorial grant invariants are incomplete",
                catalog.location(path, 1),
            )
        completion = entry.get("completion")
        if not isinstance(completion, dict) or completion != {
            "event": "property_bed_used", "next_quest_part_id": "speak_priest",
            "transition_order": ["start_next", "complete_current"],
        }:
            catalog.add_diagnostic(
                "invalid-property-completion", "tutorial completion invariants are incomplete",
                catalog.location(path, 1),
            )
        owners = entry.get("runtime_owners")
        if not isinstance(owners, dict) or owners != {
            "main": "typed_property_service",
            "classic_1x": "classic_apartment_adapter",
            "classic_entitlement_tag": entry.get("property_id"),
        } or owners.get("classic_entitlement_tag") not in tags:
            catalog.add_diagnostic(
                "invalid-property-runtime-binding",
                "typed property identity must match the Classic entitlement tag",
                catalog.location(path, 1),
            )


def load_catalog(root: Path) -> ContentCatalog:
    """Build and resolve a catalog from an Atrinik source tree."""

    root = root.resolve()
    catalog = ContentCatalog(root)
    arch_root = root / "arch"
    maps_root = root / "maps"
    if not _validate_source_roots(catalog, (arch_root, maps_root)):
        return catalog
    _load_archetypes(catalog, arch_root)
    _load_runtime_identity_tables(catalog, root / "server")
    _load_artifacts(catalog, (arch_root, maps_root))
    _load_treasures(catalog, (arch_root, maps_root))
    _load_factions(catalog, maps_root)
    _load_content_identities(catalog, maps_root)
    _load_maps(catalog, maps_root)
    _load_regions(catalog, maps_root)
    _load_interfaces(catalog, maps_root)
    _load_property_interactions(catalog, maps_root)
    catalog.check_shared_namespace(
        "server archetype", ("archetype", "artifact")
    )
    catalog.resolve_references()
    return catalog
