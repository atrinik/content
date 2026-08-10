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
            "tools.tests.test_light_review_evidence",
            "tools.tests.test_release_guidance",
            "tools.tests.test_release_line",
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
        if manifest["schema_version"] != 2 or not manifest["files"]:
            raise ValueError("runtime manifest is incomplete")
        if (
            manifest["source"]["repository"] != "atrinik/content"
            or manifest["source"]["branch"] != "1.x"
            or len(manifest["source"]["commit"]) != 40
            or manifest["release_line"] != "1.x"
            or manifest["release_version"] != "unreleased"
            or manifest["replacement_ready"] is not False
            or manifest["replacement_toolkit_package"] is not False
            or manifest["consumers"]
            != ["classic/client", "classic/editor", "classic/server"]
        ):
            raise ValueError("runtime release-line metadata is invalid")
        paths = [entry["path"] for entry in manifest["files"]]
        if paths != sorted(paths) or len(paths) != len(set(paths)):
            raise ValueError("runtime manifest paths are not canonical and unique")
        license_paths = [entry["path"] for entry in manifest["license_files"]]
        if not license_paths or not set(license_paths) <= set(paths):
            raise ValueError("runtime license manifest is incomplete")

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
    subprocess.run(
        [str(ROOT / "tools" / "validate-release-line.sh")],
        cwd=ROOT,
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
