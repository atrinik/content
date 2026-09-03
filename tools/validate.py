#!/usr/bin/env python3
"""Validate authored content boundaries and a clean runtime collection."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.content_core import audit_project
from tools.build_runtime import build as build_runtime
from tools.archetype_plurals import (
    MANIFEST_PATH,
    audit as audit_archetype_plurals,
    load_manifest,
)
from tools.m1_foundations import validate as validate_m1_foundations
from tools.release_line_parity import load_and_validate as validate_release_line_parity
from tools.validate_status_icons import validate as validate_status_icons
from tools.validate_exits import BASELINE_PATH, validate as validate_exits
from tools.validate_tiling import validate as validate_tiling


ROOT = Path(__file__).parents[1].resolve()


def main() -> int:
    required = (
        ROOT / "arch" / "COPYING",
        ROOT / "maps" / "COPYING",
        ROOT / "tools" / "COPYING",
    )
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing required license file: {path.relative_to(ROOT)}")

    for root_name in ("arch", "contracts", "maps", "editor", "schemas", "tools"):
        for path in (ROOT / root_name).rglob("*"):
            if path.is_symlink():
                raise ValueError(f"symbolic links are not allowed: {path.relative_to(ROOT)}")

    parity_report = validate_release_line_parity(ROOT)
    print(
        "Release-line parity ledger: {} commits in {} outcomes; {} tree exceptions.".format(
            parity_report["commits"],
            parity_report["outcomes"],
            parity_report["tree_exceptions"],
        ),
        flush=True,
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "tools.tests.test_content_catalog",
            "tools.tests.test_classic_target",
            "tools.tests.test_interface_compiler",
            "tools.tests.test_archetype_plurals",
            "tools.tests.test_content_contracts",
            "tools.tests.test_content_core",
            "tools.tests.test_content_schema",
            "tools.tests.test_syntax_evaluation",
            "tools.tests.test_world_content_audit",
            "tools.tests.test_m1_foundations",
            "tools.tests.test_release_guidance",
            "tools.tests.test_release_line_parity",
            "tools.tests.test_pr_metadata",
            "tools.tests.test_python_commands",
            "tools.tests.test_status_icons",
            "tools.tests.test_validate_exits",
            "tools.tests.test_validate_tiling",
        ],
        cwd=ROOT,
        check=True,
    )
    plural_report = audit_archetype_plurals(
        ROOT, load_manifest(ROOT / MANIFEST_PATH)
    )
    status_icon_report = validate_status_icons(ROOT)
    print(
        "Status icons: {} canonical imports and {} fixed statuses validated.".format(
            status_icon_report["canonical"], status_icon_report["statuses"]
        ),
        flush=True,
    )
    print(
        "Archetype plurals: {} canonical definitions complete; {} multipart or "
        "nested objects excluded.".format(
            plural_report["canonical_archetypes"], plural_report["excluded_objects"]
        ),
        flush=True,
    )
    core_audit = audit_project(ROOT, schema_root=ROOT)
    if core_audit["invalid_files"]:
        raise ValueError(
            "lossless content core rejected authored sources: {}".format(
                json.dumps(core_audit["invalid_files"], sort_keys=True)
            )
        )
    print(
        "Lossless content core: {} archetypes and {} maps are valid "
        "(diagnostics: {}).".format(
            core_audit["archetypes"],
            core_audit["maps"],
            json.dumps(core_audit["diagnostics"], sort_keys=True),
        ),
        flush=True,
    )
    exit_report = validate_exits(ROOT, BASELINE_PATH)
    if not exit_report["ok"]:
        raise ValueError(
            "authored exit validation rejected the corpus: {}".format(
                json.dumps(
                    {
                        "unapproved": exit_report["unapproved_diagnostics"],
                        "stale_baseline": exit_report["baseline"]["stale_ids"],
                    },
                    sort_keys=True,
                )
            )
        )
    print(
        "Authored exits: {} statically resolvable findings retained by the "
        "migration baseline; {} parsed maps checked.".format(
            len(exit_report["diagnostics"]),
            exit_report["scan"]["parsed_maps"],
        ),
        flush=True,
    )
    tiling_report = validate_tiling(ROOT)
    if not tiling_report["ok"]:
        raise ValueError(
            "authored tiling validation rejected the corpus: {}".format(
                json.dumps(
                    {
                        "diagnostics": len(tiling_report["diagnostics"]),
                        "scan": tiling_report["scan"],
                    },
                    sort_keys=True,
                )
            )
        )
    print(
        "Authored tiling: {} filename-redundant horizontal records remain; "
        "{} vertical matches remain deferred.".format(
            tiling_report["scan"]["redundant_horizontal"],
            tiling_report["scan"]["deferred_vertical_matches"],
        ),
        flush=True,
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "world_content_audit.py"),
            "lights",
            "--check",
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.content_schema",
            "check",
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.content_catalog",
            "validate",
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.content_contracts",
            "validate",
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.syntax_evaluation",
            "--root",
            str(ROOT),
        ],
        cwd=ROOT,
        check=True,
    )

    with tempfile.TemporaryDirectory(prefix="atrinik-content-validation-") as temporary:
        output = Path(temporary) / "runtime"
        subprocess.run(
            [sys.executable, str(ROOT / "tools" / "build_runtime.py"), "--output", str(output)],
            check=True,
        )
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if manifest["schema_version"] != 1 or not manifest["files"]:
            raise ValueError("runtime manifest is incomplete")
        paths = [entry["path"] for entry in manifest["files"]]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("runtime manifest paths are not canonical and unique")
        authored_plurals = []
        for path in sorted((ROOT / "arch").rglob("*.arc")):
            with path.open("rb") as source:
                authored_plurals.extend(
                    line.rstrip(b"\r\n")
                    for line in source
                    if line.startswith(b"name_pl ")
                )
        runtime_plurals = [
            line.rstrip(b"\r\n")
            for line in (output / "lib" / "archetypes").read_bytes().splitlines()
            if line.startswith(b"name_pl ")
        ]
        if runtime_plurals != authored_plurals:
            raise ValueError("runtime collection did not preserve authored name_pl lines")

        classic_output = Path(temporary) / "classic-runtime"
        source_commit = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        build_runtime(
            ROOT,
            classic_output,
            source_commit,
            target="classic",
        )
        classic_manifest = json.loads(
            (classic_output / "manifest.json").read_text(encoding="utf-8")
        )
        if (
            classic_manifest["schema_version"] != 2
            or classic_manifest["target"] != "classic"
            or classic_manifest["source"]
            != {
                "repository": "atrinik/content",
                "branch": "main",
                "commit": source_commit,
            }
            or classic_manifest["content_format"] != "classic-ads-v1"
            or classic_manifest["replacement_ready"] is not False
            or classic_manifest["replacement_toolkit_package"] is not False
            or not classic_manifest["license_files"]
        ):
            raise ValueError("classic runtime target metadata is invalid")

    subprocess.run(
        [
            sys.executable,
            str(ROOT / "arch" / "license_check.py"),
            "--directory",
            str(ROOT / "arch"),
            "--text-only",
        ],
        check=True,
    )
    validate_m1_foundations(ROOT, ROOT / "provenance" / "m1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
