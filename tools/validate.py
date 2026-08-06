#!/usr/bin/env python3
"""Validate authored content boundaries and a clean runtime collection."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).parents[1].resolve()


def main() -> int:
    required = (ROOT / "arch" / "COPYING", ROOT / "maps" / "COPYING", ROOT / "tools" / "COPYING")
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"missing required license file: {path.relative_to(ROOT)}")

    for root_name in ("arch", "maps", "editor", "tools"):
        for path in (ROOT / root_name).rglob("*"):
            if path.is_symlink():
                raise ValueError(f"symbolic links are not allowed: {path.relative_to(ROOT)}")

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
        [sys.executable, str(ROOT / "arch" / "license_check.py"), "--directory", str(ROOT / "arch"), "--text-only"],
        check=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

