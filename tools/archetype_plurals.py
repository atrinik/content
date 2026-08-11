"""Reviewed, drift-safe one-time migration for canonical archetype plurals."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import secrets
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.content_catalog import load_catalog
from tools.content_core import parse_bytes, prepare_transaction, publish_transaction
from tools.content_core.errors import ContentCoreError
from tools.content_core.operations import result_digest
from tools.content_core.transaction import MAX_TRANSACTION_FILES
from tools.content_core.transaction import PreparedTransaction


MANIFEST_PATH = Path("tools/archetype-plurals-v1.json")
COMPARISON_PATH = Path("tools/archetype-plurals-cross-line-v1.json")
RECOVERY_JOURNAL_PATH = Path("build/archetype-plural-migration-recovery-v1.json")
RECOVERY_JOURNAL_PENDING_PATH = Path(
    "build/archetype-plural-migration-recovery-v1.pending"
)
REVIEWED_MANIFEST_SHA256 = "740e28c4f6ce9f45d031224f3ff91d423754228c789048352557648d4d35e100"
LINES = {
    "1.x": {
        "baseline_sha": "ead72ef831444c874f65da841498924bab625e99",
        "delivery_branch": "fix/62-explicit-plurals-1x",
    },
    "main": {
        "baseline_sha": "440b45a85603642f6edd37bb5bf45c2034ed0410",
        "delivery_branch": "fix/62-explicit-plurals-main",
    },
}


class PluralMigrationError(ValueError):
    """The reviewed vocabulary or checked-out corpus has drifted."""


def _git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=check,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def identify_line(root: Path, *, migration: bool = True) -> str:
    """Bind the migration to one exact reviewed baseline and delivery branch."""

    branch = _git(root, "branch", "--show-current")
    head = _git(root, "rev-parse", "HEAD")
    matches = []
    for line, coordinates in LINES.items():
        baseline = coordinates["baseline_sha"]
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", baseline, head],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            matches.append(line)
        elif result.returncode != 1:
            raise PluralMigrationError("cannot verify reviewed baseline {}".format(baseline))
    if len(matches) != 1:
        raise PluralMigrationError(
            "HEAD must descend from exactly one reviewed plural baseline"
        )
    line = matches[0]
    expected_branches = {LINES[line]["delivery_branch"]}
    if not migration:
        expected_branches.add(line)
    if branch not in expected_branches:
        raise PluralMigrationError(
            "reviewed plural operation for {} requires one of branches {}, found {}".format(
                line, sorted(expected_branches), branch or "detached HEAD"
            )
        )
    return line


def _canonical_nodes(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    catalog = load_catalog(root)
    if catalog.has_errors:
        raise PluralMigrationError(
            "content catalog is invalid: {}".format(
                "; ".join(item.format() for item in catalog.diagnostics[:10])
            )
        )
    definitions = [
        item for item in catalog.definitions if item.content_id.domain == "archetype"
    ]
    by_path: dict[str, list[Any]] = defaultdict(list)
    for definition in definitions:
        by_path[definition.location.path].append(definition)

    entries: dict[str, dict[str, Any]] = {}
    documents = {}
    for relative in sorted(by_path):
        source = (root / relative).read_bytes()
        document = parse_bytes(
            source, path=relative, format_name="archetype", schema_root=root
        )
        documents[relative] = document
        nodes = {(node.opener_span.line, node.name): node for node in document.objects}
        for definition in by_path[relative]:
            archetype_id = definition.content_id.key
            key = (definition.location.line, archetype_id)
            node = nodes.get(key)
            if node is None or node.depth != 0:
                raise PluralMigrationError(
                    "catalog definition {} does not resolve to its canonical object node at {}".format(
                        archetype_id, definition.location.display()
                    )
                )
            names = node.field_ids("object.name")
            plurals = node.field_ids("object.name_pl")
            types = node.field_ids("object.type")
            if len(names) > 1 or len(types) > 1:
                raise PluralMigrationError(
                    "{} has duplicate singular-name or type fields".format(archetype_id)
                )
            entries[archetype_id] = {
                "archetype_id": archetype_id,
                "singular": names[0].typed_value if names else archetype_id,
                "object_type": str(types[0].typed_value) if types else "0",
                "explicit_singular": bool(names),
                "sys_object": any(
                    field.typed_value is True
                    for field in node.field_ids("object.sys_object")
                ),
                "path": relative,
                "node": node,
                "plurals": plurals,
                "source_sha256": result_digest(source),
            }
    if len(entries) != len(definitions):
        raise PluralMigrationError("canonical archetype IDs are not unique")
    return entries, documents


def inventory(root: Path) -> Mapping[str, Any]:
    entries, documents = _canonical_nodes(root)
    explicit = sum(item["explicit_singular"] for item in entries.values())
    continuations = sum(document.multipart_continuations for document in documents.values())
    nested = sum(
        node.depth > 0 for document in documents.values() for node in document.objects
    )
    return {
        "schema_version": 1,
        "kind": "archetype-plural-inventory",
        "archetypes": len(entries),
        "archetype_files": len(documents),
        "explicit_singulars": explicit,
        "object_id_fallbacks": len(entries) - explicit,
        "internal_controllers": sum(item["sys_object"] for item in entries.values()),
        "multipart_continuations": continuations,
        "nested_objects": nested,
        "with_name_pl": sum(bool(item["plurals"]) for item in entries.values()),
        "rows": [
            {
                "archetype_id": item["archetype_id"],
                "singular": item["singular"],
                "object_type": item["object_type"],
                "name_pl": (
                    item["plurals"][0].typed_value
                    if len(item["plurals"]) == 1
                    else None
                ),
            }
            for item in sorted(entries.values(), key=lambda value: value["archetype_id"])
        ],
    }


IRREGULAR = {
    "abyss": "abysses",
    "ancus": "ancuses",
    "calf": "calves",
    "child": "children",
    "chilli": "chillies",
    "cactus": "cacti",
    "compass": "compasses",
    "cuirass": "cuirasses",
    "cutlass": "cutlasses",
    "cyclops": "cyclopes",
    "dwarf": "dwarves",
    "dress": "dresses",
    "elf": "elves",
    "foot": "feet",
    "goose": "geese",
    "gladius": "gladii",
    "half": "halves",
    "knife": "knives",
    "leaf": "leaves",
    "life": "lives",
    "loaf": "loaves",
    "man": "men",
    "mouse": "mice",
    "markswoman": "markswomen",
    "oarman": "oarsmen",
    "oclunus": "ocluni",
    "person": "people",
    "portcullis": "portcullises",
    "priestess": "priestesses",
    "quaterstaff": "quaterstaves",
    "sarcophagus": "sarcophagi",
    "self": "selves",
    "shelf": "shelves",
    "snowman": "snowmen",
    "sorceress": "sorceresses",
    "staff": "staves",
    "thief": "thieves",
    "tooth": "teeth",
    "tomato": "tomatoes",
    "wife": "wives",
    "wolf": "wolves",
    "woman": "women",
}
UNCHANGED_WORDS = {
    "dice",
    "deer",
    "equipment",
    "fish",
    "starfish",
    "information",
    "moose",
    "series",
    "sheep",
    "species",
}
PHRASE_OVERRIDES = {
    "ball and chain": ("balls and chains", "review:coordinated-compound"),
    "bottled water": ("bottles of water", "review:container-compound"),
    "burnt out torch": ("burnt out torches", "review:required-issue-vocabulary"),
    "end of inventory": ("End of inventory", "review:internal-action-label"),
    "ladder going down": ("ladders going down", "review:postpositive-compound"),
    "ladder going up": ("ladders going up", "review:postpositive-compound"),
    "next group of items": ("Next group of items", "review:internal-action-label"),
    "previous group of items": ("Previous group of items", "review:internal-action-label"),
    "stairs going down": ("stairs going down", "review:already-plural-compound"),
    "stairs going up": ("stairs going up", "review:already-plural-compound"),
    "start of inventory": ("Start of inventory", "review:internal-action-label"),
    "torch": ("torches", "review:required-issue-vocabulary"),
    "waterfall huge": ("waterfalls huge", "review:postpositive-compound"),
}
MASS_OR_INVARIANT = {
    "agnes",
    "axle grease",
    "blood",
    "candlelight",
    "cured bacon",
    "dirt",
    "dried mint",
    "dried pipeweed",
    "dust",
    "earth",
    "ectoplasm",
    "fire",
    "flint and steel",
    "flu",
    "fog",
    "glue",
    "grain",
    "ice",
    "lamp oil",
    "lava",
    "lead",
    "leprosy",
    "lightning",
    "luggage",
    "mercury",
    "paper",
    "poison",
    "pottery",
    "raw mana",
    "rigging",
    "rubbish",
    "sand",
    "smallpox",
    "snow",
    "staple food",
    "straw",
    "strange glowing fog",
    "virgin olive oil",
    "water",
    "wealth",
    "wood",
    "yew tree pulp",
}
FALLBACK_UNCHANGED = {
    "base_info",
    "beacon",
    "blocked",
    "client_map_info",
    "damager",
    "depletion",
    "duplicator",
    "empty_archetype",
    "falling",
    "fog",
    "glue",
    "immunity",
    "invis_exit",
    "lead",
    "magic_mirror",
    "magic_mouth",
    "mercury",
    "player_force",
    "quest_container",
    "rand_drop",
    "random_treasure",
    "slower",
    "slowness",
    "sound_ambient",
    "spawn_info",
    "spawn_point",
    "swarm_spell",
    "symptom",
    "trans",
    "waypoint",
    "wealth",
}


def _preserve_case(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _plural_word(word: str) -> tuple[str, str]:
    lower = word.casefold()
    if lower in UNCHANGED_WORDS:
        return word, "review:unchanged-noun"
    if lower in IRREGULAR:
        return _preserve_case(word, IRREGULAR[lower]), "review:irregular"
    if lower.endswith("y") and len(lower) > 1 and lower[-2] not in "aeiou":
        return word[:-1] + _preserve_case(word[-1:], "ies"), "rule:consonant-y"
    if lower.endswith(("ch", "sh", "x", "z")):
        return word + "es", "rule:sibilant-es"
    if lower.endswith("s"):
        return word, "review:already-plural-or-mass"
    return word + "s", "rule:regular-s"


def propose_plural(
    singular: str, object_type: str, explicit: bool, *, sys_object: bool = False
) -> tuple[str, str]:
    lower = singular.casefold()
    if lower in PHRASE_OVERRIDES:
        return PHRASE_OVERRIDES[lower]
    if sys_object or object_type in {"88", "110", "114"}:
        return singular, "review:internal-controller"
    if lower.startswith("close the "):
        return singular, "review:internal-action-label"
    if object_type in {"29", "43"}:
        return singular, "review:spell-or-skill-label"
    if (
        lower in MASS_OR_INVARIANT
        or lower in {"armour", "mail"}
        or lower.endswith((" armour", " mail", "bread"))
    ):
        return singular, "review:mass-or-invariant"
    if object_type == "50" and " " not in singular and singular[:1].isupper():
        return singular, "review:proper-name"
    head = singular
    tail = ""
    for separator in (" of ", " for ", " in ", " on ", " from ", " with ", " to "):
        if separator in singular:
            head, remainder = singular.split(separator, 1)
            tail = separator + remainder
            break
    words = head.split(" ")
    plural, rule = _plural_word(words[-1])
    value = " ".join(words[:-1] + [plural]) + tail
    prefix = "review:object-id-fallback+" if not explicit else ""
    return value, prefix + rule


def proposed_manifest(root: Path) -> Mapping[str, Any]:
    entries, _ = _canonical_nodes(root)
    rows = []
    for archetype_id in sorted(entries):
        entry = entries[archetype_id]
        if not entry["explicit_singular"] and archetype_id in FALLBACK_UNCHANGED:
            name_pl = entry["singular"]
            classification = "review:object-id-fallback-invariant"
        else:
            name_pl, classification = propose_plural(
                entry["singular"],
                entry["object_type"],
                entry["explicit_singular"],
                sys_object=entry["sys_object"],
            )
            if not entry["explicit_singular"]:
                classification = "review:object-id-fallback-count-noun"
        rows.append(
            {
                "archetype_id": archetype_id,
                "singular": entry["singular"],
                "object_type": entry["object_type"],
                "name_pl": name_pl,
                "classification": classification,
            }
        )
    return {
        "schema_version": 1,
        "kind": "archetype-plural-manifest",
        "issue": "atrinik/content#62",
        "lines": LINES,
        "rows": rows,
    }


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def load_manifest(path: Path) -> Mapping[str, Any]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != REVIEWED_MANIFEST_SHA256:
        raise PluralMigrationError("plural manifest does not match the reviewed digest")
    manifest = _load_json(path)
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version", "kind", "issue", "lines", "rows"
    }:
        raise PluralMigrationError("plural manifest root is not closed")
    if (
        manifest["schema_version"] != 1
        or manifest["kind"] != "archetype-plural-manifest"
        or manifest["issue"] != "atrinik/content#62"
        or manifest["lines"] != LINES
    ):
        raise PluralMigrationError("plural manifest identity or baselines drifted")
    rows = manifest["rows"]
    expected_keys = {
        "archetype_id", "singular", "object_type", "name_pl", "classification"
    }
    if (
        not isinstance(rows, list)
        or not rows
        or any(not isinstance(row, dict) or set(row) != expected_keys for row in rows)
    ):
        raise PluralMigrationError("plural manifest rows are not closed")
    ids = [row["archetype_id"] for row in rows]
    if ids != sorted(set(ids)):
        raise PluralMigrationError("plural manifest IDs must be sorted and unique")
    for row in rows:
        if any(
            not isinstance(row[key], str) or not row[key] or row[key] != row[key].strip()
            for key in expected_keys
        ):
            raise PluralMigrationError(
                "plural manifest row {} contains empty or untrimmed text".format(
                    row.get("archetype_id", "<unknown>")
                )
            )
        if not row["classification"].startswith("review:"):
            raise PluralMigrationError(
                "plural manifest row {} is still an unreviewed proposal".format(
                    row["archetype_id"]
                )
            )
    return manifest


def _checked_rows(
    root: Path, manifest: Mapping[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[Mapping[str, Any]]]:
    entries, _ = _canonical_nodes(root)
    rows = manifest["rows"]
    by_id = {row["archetype_id"]: row for row in rows}
    actual_ids = set(entries)
    expected_ids = set(by_id)
    if actual_ids != expected_ids:
        raise PluralMigrationError(
            "catalog ID drift: missing={}, unexpected={}".format(
                sorted(expected_ids - actual_ids), sorted(actual_ids - expected_ids)
            )
        )
    for archetype_id, entry in entries.items():
        row = by_id[archetype_id]
        if entry["singular"] != row["singular"] or entry["object_type"] != row["object_type"]:
            raise PluralMigrationError(
                "reviewed singular/type drift for {}: expected {!r}/{}, found {!r}/{}".format(
                    archetype_id,
                    row["singular"],
                    row["object_type"],
                    entry["singular"],
                    entry["object_type"],
                )
            )
        if len(entry["plurals"]) > 1:
            raise PluralMigrationError("{} has duplicate name_pl fields".format(archetype_id))
        if entry["plurals"] and entry["plurals"][0].typed_value != row["name_pl"]:
            raise PluralMigrationError(
                "{} has divergent existing name_pl {!r}".format(
                    archetype_id, entry["plurals"][0].typed_value
                )
            )
    return entries, rows


def _transactions(
    entries: Mapping[str, Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    operations: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    sources = {}
    for row in rows:
        entry = entries[row["archetype_id"]]
        if entry["plurals"]:
            continue
        node = entry["node"]
        operations[entry["path"]].append(
            {
                "kind": "set-property",
                "node_handle": node.handle,
                "node_fingerprint": node.fingerprint,
                "field_id": "object.name_pl",
                "value": row["name_pl"],
            }
        )
        sources[entry["path"]] = entry["source_sha256"]
    files = [
        {
            "path": path,
            "format": "archetype",
            "base_sha256": sources[path],
            "operations": operations[path],
        }
        for path in sorted(operations)
    ]
    return [
        {
            "schema_version": 1,
            "kind": "content-transaction",
            "files": files[index : index + MAX_TRANSACTION_FILES],
        }
        for index in range(0, len(files), MAX_TRANSACTION_FILES)
    ]


def _recovery_transactions(
    entries: Mapping[str, Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]
) -> list[Mapping[str, Any]]:
    operations: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    sources = {}
    for row in rows:
        entry = entries[row["archetype_id"]]
        if not entry["plurals"]:
            continue
        node = entry["node"]
        operations[entry["path"]].append(
            {
                "kind": "unset-property",
                "node_handle": node.handle,
                "node_fingerprint": node.fingerprint,
                "field_id": "object.name_pl",
            }
        )
        sources[entry["path"]] = entry["source_sha256"]
    files = [
        {
            "path": path,
            "format": "archetype",
            "base_sha256": sources[path],
            "operations": operations[path],
        }
        for path in sorted(operations)
    ]
    return [
        {
            "schema_version": 1,
            "kind": "content-transaction",
            "files": files[index : index + MAX_TRANSACTION_FILES],
        }
        for index in range(0, len(files), MAX_TRANSACTION_FILES)
    ]


def _publish_prepared(
    root: Path,
    prepared: Sequence[PreparedTransaction],
    failure_after: int | None = None,
) -> None:
    preexisting, artifact_token = _open_recovery_journal(root)
    combined = PreparedTransaction(
        tuple(item for transaction in prepared for item in transaction.files)
    )
    try:
        publish_transaction(
            root,
            combined,
            failure_after=failure_after,
            artifact_token=artifact_token,
        )
    except ContentCoreError as error:
        if error.code == "transaction-rollback-failed":
            raise
        _close_recovery_journal(
            root,
            preexisting,
            {item.path.parent for item in combined.files},
            artifact_token,
        )
        raise
    else:
        _close_recovery_journal(
            root,
            preexisting,
            {item.path.parent for item in combined.files},
            artifact_token,
        )


def _transaction_artifacts(root: Path, artifact_token: str | None = None) -> set[str]:
    artifacts = set()
    token = "{}-".format(artifact_token) if artifact_token else ""
    for pattern in (
        ".*-content-stage-{}*.tmp".format(token),
        ".*-content-backup-{}*.tmp".format(token),
    ):
        for path in (root / "arch").rglob(pattern):
            if path.is_symlink() or not path.is_file():
                raise PluralMigrationError(
                    "unsafe transaction artifact at {}".format(path)
                )
            artifacts.add(path.relative_to(root).as_posix())
    return artifacts


def _open_recovery_journal(root: Path) -> tuple[set[str], str]:
    path = root / RECOVERY_JOURNAL_PATH
    pending = root / RECOVERY_JOURNAL_PENDING_PATH
    if path.exists():
        if pending.exists():
            raise PluralMigrationError(
                "plural recovery journal has a conflicting pending write"
            )
        value = _load_json(path)
        if (
            not isinstance(value, dict)
            or value.get("schema_version") != 1
            or value.get("kind") != "archetype-plural-recovery-journal"
            or value.get("manifest_sha256") != REVIEWED_MANIFEST_SHA256
            or not isinstance(value.get("artifact_token"), str)
            or len(value["artifact_token"]) != 32
            or any(
                character not in "0123456789abcdef"
                for character in value["artifact_token"]
            )
            or not isinstance(value.get("preexisting_artifacts"), list)
            or any(not isinstance(item, str) for item in value["preexisting_artifacts"])
        ):
            raise PluralMigrationError("plural recovery journal is invalid")
        return set(value["preexisting_artifacts"]), value["artifact_token"]
    if pending.exists():
        pending.unlink()
        _sync_directory(pending.parent)
    preexisting = _transaction_artifacts(root)
    artifact_token = secrets.token_hex(16)
    value = {
        "schema_version": 1,
        "kind": "archetype-plural-recovery-journal",
        "manifest_sha256": REVIEWED_MANIFEST_SHA256,
        "artifact_token": artifact_token,
        "preexisting_artifacts": sorted(preexisting),
    }
    pending.parent.mkdir(parents=True, exist_ok=True)
    with pending.open("x", encoding="utf-8", newline="\n") as destination:
        json.dump(value, destination, indent=2)
        destination.write("\n")
        destination.flush()
        os.fsync(destination.fileno())
    os.replace(pending, path)
    _sync_directory(path.parent)
    return preexisting, artifact_token


def _sync_directory(directory: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(
        directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _close_recovery_journal(
    root: Path,
    preexisting: set[str],
    sync_directories: set[Path] | None = None,
    artifact_token: str | None = None,
) -> None:
    directories = set(sync_directories or ())
    for relative in sorted(
        _transaction_artifacts(root, artifact_token) - preexisting
    ):
        path = root / relative
        path.unlink()
        directories.add(path.parent)
    for directory in sorted(directories):
        _sync_directory(directory)
    journal = root / RECOVERY_JOURNAL_PATH
    journal.unlink(missing_ok=True)
    _sync_directory(journal.parent)


@contextmanager
def _operation_lock(root: Path):
    identity = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()
    path = Path(tempfile.gettempdir()) / "atrinik-plural-{}.lock".format(identity)
    with path.open("a+b") as lock:
        lock.seek(0)
        if lock.read(1) == b"":
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise PluralMigrationError(
                "another plural migration or recovery is active"
            ) from error
        try:
            yield
        finally:
            lock.seek(0)
            if os.name == "nt":
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _serialized_operation(function):
    @wraps(function)
    def serialized(root: Path, *args, **kwargs):
        with _operation_lock(root):
            return function(root, *args, **kwargs)

    return serialized


@_serialized_operation
def migrate(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    apply: bool = False,
    check_git: bool = True,
    publish_failure_after: int | None = None,
) -> Mapping[str, Any]:
    if check_git and manifest != load_manifest(root / MANIFEST_PATH):
        raise PluralMigrationError(
            "migration input differs from the repository-owned reviewed manifest"
        )
    line = identify_line(root) if check_git else "fixture"
    entries, rows = _checked_rows(root, manifest)
    present = sum(bool(entry["plurals"]) for entry in entries.values())
    if present not in (0, len(entries)):
        raise PluralMigrationError(
            "partial plural migration detected: {}/{} canonical archetypes satisfied".format(
                present, len(entries)
            )
        )
    if present == len(entries):
        return {
            "schema_version": 1,
            "kind": "archetype-plural-migration",
            "line": line,
            "dry_run": not apply,
            "applied": False,
            "status": "already-satisfied",
            "archetypes": len(entries),
            "files": 0,
            "batches": 0,
        }
    if check_git:
        baseline = LINES[line]["baseline_sha"]
        if _git(root, "rev-parse", "HEAD") != baseline:
            raise PluralMigrationError(
                "unapplied migration requires exact reviewed baseline {}".format(
                    baseline
                )
            )
        unchanged = subprocess.run(
            ["git", "-C", str(root), "diff", "--quiet", baseline, "--", "arch"],
            check=False,
        )
        if unchanged.returncode == 1:
            raise PluralMigrationError(
                "archetype sources differ from the exact reviewed baseline"
            )
        if unchanged.returncode != 0:
            raise PluralMigrationError("cannot verify exact reviewed archetype sources")
    transactions = _transactions(entries, rows)
    prepared = [prepare_transaction(root, transaction, schema_root=root) for transaction in transactions]
    if apply:
        _publish_prepared(root, prepared, publish_failure_after)
    return {
        "schema_version": 1,
        "kind": "archetype-plural-migration",
        "line": line,
        "dry_run": not apply,
        "applied": apply,
        "status": "applied" if apply else "prepared",
        "archetypes": len(entries),
        "files": sum(len(item.files) for item in prepared),
        "batches": len(prepared),
        "operations": sum(
            file.operation_count for item in prepared for file in item.files
        ),
    }


@_serialized_operation
def recover(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    apply: bool = False,
    check_git: bool = True,
) -> Mapping[str, Any]:
    """Remove only a manifest-matching interrupted partial migration."""

    if check_git and manifest != load_manifest(root / MANIFEST_PATH):
        raise PluralMigrationError(
            "recovery input differs from the repository-owned reviewed manifest"
        )
    line = identify_line(root) if check_git else "fixture"
    journal = root / RECOVERY_JOURNAL_PATH
    interrupted_publication = journal.exists()
    preexisting, artifact_token = (
        _open_recovery_journal(root)
        if interrupted_publication
        else (set(), None)
    )
    entries, rows = _checked_rows(root, manifest)
    present = sum(bool(entry["plurals"]) for entry in entries.values())
    if present == 0:
        if apply and interrupted_publication:
            _close_recovery_journal(
                root, preexisting, artifact_token=artifact_token
            )
        return {
            "schema_version": 1,
            "kind": "archetype-plural-recovery",
            "line": line,
            "dry_run": not apply,
            "applied": False,
            "status": "already-recovered",
            "archetypes": 0,
            "files": 0,
            "batches": 0,
        }
    if present == len(entries) and interrupted_publication:
        if apply:
            _close_recovery_journal(
                root, preexisting, artifact_token=artifact_token
            )
        return {
            "schema_version": 1,
            "kind": "archetype-plural-recovery",
            "line": line,
            "dry_run": not apply,
            "applied": False,
            "status": "publication-complete",
            "archetypes": present,
            "files": 0,
            "batches": 0,
        }
    if present == len(entries):
        raise PluralMigrationError(
            "recovery requires a partial reviewed migration, found {}/{}".format(
                present, len(entries)
            )
        )
    if check_git:
        baseline = LINES[line]["baseline_sha"]
        result = subprocess.run(
            [
                "git", "-C", str(root), "diff", "--no-ext-diff", "--unified=0",
                baseline, "--", ":(glob)arch/**/*.arc",
            ],
            check=True, capture_output=True, text=True,
        )
        additions = Counter()
        for line_text in result.stdout.splitlines():
            if line_text.startswith(("+++", "---")):
                continue
            if line_text.startswith("+") and line_text[1:].startswith("name_pl "):
                additions[line_text[1:].removeprefix("name_pl ")] += 1
            elif line_text.startswith(("+", "-")):
                raise PluralMigrationError(
                    "partial recovery refuses unrelated archetype-source changes"
                )
        expected = Counter(
            entry["plurals"][0].typed_value
            for entry in entries.values()
            if entry["plurals"]
        )
        if additions != expected:
            raise PluralMigrationError(
                "partial recovery diff does not match reviewed plural additions"
            )
    transactions = _recovery_transactions(entries, rows)
    prepared = [
        prepare_transaction(root, transaction, schema_root=root)
        for transaction in transactions
    ]
    if apply:
        _publish_prepared(root, prepared)
    return {
        "schema_version": 1,
        "kind": "archetype-plural-recovery",
        "line": line,
        "dry_run": not apply,
        "applied": apply,
        "status": "recovered" if apply else "prepared",
        "archetypes": present,
        "files": sum(len(item.files) for item in prepared),
        "batches": len(prepared),
    }


def audit(root: Path, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    entries, rows = _checked_rows(root, manifest)
    expected = {row["archetype_id"]: row["name_pl"] for row in rows}
    failures = []
    canonical = {
        (entry["path"], entry["node"].opener_span.line, archetype_id)
        for archetype_id, entry in entries.items()
    }
    _, documents = _canonical_nodes(root)
    for archetype_id, entry in entries.items():
        if len(entry["plurals"]) != 1:
            failures.append("{} does not have exactly one name_pl".format(archetype_id))
        elif entry["plurals"][0].typed_value != expected[archetype_id]:
            failures.append("{} does not match its reviewed name_pl".format(archetype_id))
    excluded = 0
    for relative, document in documents.items():
        for node in document.objects:
            key = (relative, node.opener_span.line, node.name)
            if key in canonical:
                continue
            excluded += 1
            if node.field_ids("object.name_pl"):
                failures.append(
                    "excluded multipart/nested object has name_pl at {}:{}".format(
                        relative, node.opener_span.line
                    )
                )
    if failures:
        raise PluralMigrationError("; ".join(failures[:20]))
    return {
        "schema_version": 1,
        "kind": "archetype-plural-audit",
        "canonical_archetypes": len(entries),
        "canonical_name_pl": len(entries),
        "excluded_objects": excluded,
        "failures": [],
    }


def audit_source_delta(root: Path, manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    """Prove every archetype-source change is one reviewed name_pl addition."""

    line = identify_line(root, migration=False)
    baseline = LINES[line]["baseline_sha"]
    result = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff",
            "--no-ext-diff",
            "--unified=0",
            baseline,
            "--",
            ":(glob)arch/**/*.arc",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    actual = Counter()
    additions = 0
    deletions = 0
    for line_text in result.stdout.splitlines():
        if line_text.startswith("+++") or line_text.startswith("---"):
            continue
        if line_text.startswith("+"):
            value = line_text[1:]
            if not value.startswith("name_pl "):
                raise PluralMigrationError(
                    "archetype source delta contains a non-name_pl addition: {}".format(
                        value
                    )
                )
            additions += 1
            actual[value.removeprefix("name_pl ")] += 1
        elif line_text.startswith("-"):
            deletions += 1
    expected = Counter(row["name_pl"] for row in manifest["rows"])
    if deletions or additions != len(manifest["rows"]) or actual != expected:
        raise PluralMigrationError(
            "archetype source delta is not exactly the reviewed name_pl additions"
        )
    return {
        "schema_version": 1,
        "kind": "archetype-plural-source-delta-audit",
        "line": line,
        "baseline_sha": baseline,
        "additions": additions,
        "deletions": deletions,
        "other_changes": 0,
    }


def _assert_comparison_lines(left_line: str, right_line: str) -> None:
    if (left_line, right_line) != ("main", "1.x"):
        raise PluralMigrationError(
            "cross-line comparison requires main as --root and 1.x as --other-root"
        )


def compare(root: Path, other_root: Path) -> Mapping[str, Any]:
    left_line = identify_line(root, migration=False)
    right_line = identify_line(other_root, migration=False)
    _assert_comparison_lines(left_line, right_line)
    audit_source_delta(root, load_manifest(root / MANIFEST_PATH))
    audit_source_delta(other_root, load_manifest(other_root / MANIFEST_PATH))
    left = {row["archetype_id"]: row for row in inventory(root)["rows"]}
    right = {row["archetype_id"]: row for row in inventory(other_root)["rows"]}
    shared = sorted(set(left) & set(right))
    differences = []
    for archetype_id in shared:
        for field in ("singular", "object_type", "name_pl"):
            if left[archetype_id][field] != right[archetype_id][field]:
                differences.append(
                    {
                        "archetype_id": archetype_id,
                        "field": field,
                        "left": left[archetype_id][field],
                        "right": right[archetype_id][field],
                    }
                )
    return {
        "schema_version": 1,
        "kind": "archetype-plural-cross-line-comparison",
        "issue": "atrinik/content#62",
        "left_baseline": LINES[left_line]["baseline_sha"],
        "right_baseline": LINES[right_line]["baseline_sha"],
        "shared_archetypes": len(shared),
        "left_only": sorted(set(left) - set(right)),
        "right_only": sorted(set(right) - set(left)),
        "differences": differences,
    }


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=".{}-".format(path.name), suffix=".tmp", delete=False
        ) as destination:
            temporary = Path(destination.name)
            json.dump(value, destination, indent=2, sort_keys=False)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=(
            "inventory", "propose", "migrate", "recover", "audit",
            "audit-source-delta", "compare"
        )
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--other-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(argv)
    root = options.root.resolve()
    manifest_path = options.manifest or root / MANIFEST_PATH
    try:
        if (
            options.command in {"migrate", "recover"}
            and not options.apply
            and options.output is not None
        ):
            raise PluralMigrationError(
                "migration and recovery dry-runs are stdout-only; --output requires --apply"
            )
        if options.command == "inventory":
            result = inventory(root)
        elif options.command == "propose":
            result = proposed_manifest(root)
        elif options.command == "migrate":
            result = migrate(root, load_manifest(manifest_path), apply=options.apply)
        elif options.command == "recover":
            result = recover(root, load_manifest(manifest_path), apply=options.apply)
        elif options.command == "audit":
            result = audit(root, load_manifest(manifest_path))
        elif options.command == "audit-source-delta":
            result = audit_source_delta(root, load_manifest(manifest_path))
        else:
            if options.other_root is None:
                raise PluralMigrationError("compare requires --other-root")
            result = compare(root, options.other_root.resolve())
        if options.output is not None:
            output = options.output if options.output.is_absolute() else root / options.output
            _atomic_json(output, result)
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (ContentCoreError, OSError, PluralMigrationError, ValueError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
