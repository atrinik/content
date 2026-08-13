#!/usr/bin/env python3
"""Audit every standard and special Classic temple service provider."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parents[1].resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "maps" / "python"))

import TempleServices
from tools.content_core import parse_bytes


def interface_rules(root: Path):
    rules = defaultdict(set)
    interface_root = root / "maps" / "interfaces"
    for path in sorted(interface_root.rglob("*.xml")):
        relative = path.relative_to(root / "maps").as_posix()
        key = "/" + relative
        document = ET.parse(path)
        for element in document.getroot().iter("interface"):
            if (element.get("inherit") or "").startswith("Temple.Temple"):
                rules[key].add(element.get("npc"))
    return dict(rules)


def map_paths(root: Path, interfaces):
    needles = tuple(
        ("race " + interface + "\n").encode("utf-8")
        for interface in interfaces
    )
    for path in sorted((root / "maps").rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        source = path.read_bytes()
        if source.startswith(b"arch map\n") and any(
            needle in source for needle in needles
        ):
            yield path, source


def inventory(root: Path):
    root = root.resolve(strict=True)
    rules = interface_rules(root)
    rows = []
    for path, source in map_paths(root, rules):
        relative = path.relative_to(root).as_posix()
        document = parse_bytes(
            source,
            path=relative,
            format_name="map",
            schema_root=root,
        )
        for event in document.objects:
            interface = event.last_value("race")
            if interface not in rules or event.parent_handle is None:
                continue
            parent = document.node(event.parent_handle)
            name = parent.last_value("name", parent.name)
            npcs = rules[interface]
            if None not in npcs and name not in npcs:
                continue
            provider_id = next((
                provider_id
                for provider_id, provider in TempleServices.PROVIDERS.items()
                if provider.name == name and provider.map_path == relative
            ), None)
            rows.append({
                "provider_id": provider_id,
                "name": name,
                "map_path": relative,
                "interface": interface.removeprefix("/interfaces/"),
                "combat_level": int(parent.last_value("level", "1")),
                "line": parent.opener_span.line,
            })
    return rows


def validate(rows, providers):
    errors = []
    by_id = defaultdict(list)
    for row in rows:
        if row["provider_id"] is None:
            errors.append(
                "{}:{}: {} has no provider registry entry".format(
                    row["map_path"], row["line"], row["name"]
                )
            )
            continue
        by_id[row["provider_id"]].append(row)

    expected_ids = set(providers)
    actual_ids = set(by_id)
    for provider_id in sorted(expected_ids - actual_ids):
        errors.append("registered provider is not authored: {}".format(provider_id))
    for provider_id in sorted(actual_ids - expected_ids):
        errors.append("authored provider is not registered: {}".format(provider_id))
    for provider_id in sorted(expected_ids & actual_ids):
        authored = by_id[provider_id]
        if len(authored) != 1:
            errors.append(
                "provider id {} is authored {} times".format(
                    provider_id, len(authored)
                )
            )
            continue
        row = authored[0]
        provider = providers[provider_id]
        expected = {
            "name": provider.name,
            "map_path": provider.map_path,
            "interface": provider.interface,
            "combat_level": provider.combat_level,
        }
        for field, value in expected.items():
            if row[field] != value:
                errors.append(
                    "{} {} mismatch: authored {!r}, registered {!r}".format(
                        provider_id, field, row[field], value
                    )
                )
        if provider.service_rank not in (20, 40, 60, 100):
            errors.append(
                "{} has unsupported service rank {}".format(
                    provider_id, provider.service_rank
                )
            )
    return errors


def audit(root: Path):
    rows = inventory(root)
    errors = validate(rows, TempleServices.PROVIDERS)
    return {
        "providers": len(rows),
        "registered": len(TempleServices.PROVIDERS),
        "errors": errors,
    }


def main(argv=None):
    root = Path(argv[0] if argv else ".")
    report = audit(root)
    if report["errors"]:
        for error in report["errors"]:
            print(error, file=sys.stderr)
        return 1
    print(
        "Temple services: {} providers match the explicit capability registry.".format(
            report["providers"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
