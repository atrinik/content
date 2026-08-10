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
from tools.m1_foundations import validate as validate_m1_foundations


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

    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "tools.tests.test_content_catalog",
            "tools.tests.test_content_contracts",
            "tools.tests.test_content_core",
            "tools.tests.test_content_schema",
            "tools.tests.test_syntax_evaluation",
            "tools.tests.test_world_content_audit",
            "tools.tests.test_m1_foundations",
            "tools.tests.test_release_guidance",
            "tools.tests.test_python_commands",
        ],
        cwd=ROOT,
        check=True,
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
