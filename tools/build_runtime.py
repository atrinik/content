#!/usr/bin/env python3
"""Build an isolated, digest-addressed Atrinik runtime content tree."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def copy_attribution(source: Path, output: Path) -> None:
    for component in ("arch", "maps", "tools"):
        root = source / component
        for path in sorted(root.rglob("LICENSE")):
            target = output / "attribution" / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        copying = root / "COPYING"
        if copying.is_file():
            target = output / "attribution" / component / "COPYING"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(copying, target)


def create_manifest(output: Path, source_commit: str) -> None:
    files = []
    paths = sorted(output.rglob("*"), key=lambda path: path.relative_to(output).as_posix())
    for path in paths:
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append(
            {
                "path": path.relative_to(output).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
    manifest = {
        "schema_version": 1,
        "source_commit": source_commit,
        "files": files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def build(source: Path, output: Path, source_commit: str) -> None:
    source = source.resolve()
    output = output.resolve()
    build_root = source / "build"
    if output == source or (
        source in output.parents
        and output != build_root
        and build_root not in output.parents
    ):
        raise ValueError("output must not replace an authored source directory")
    if output.exists():
        shutil.rmtree(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="atrinik-content-") as temporary:
        staging = Path(temporary)
        for component in ("arch", "maps", "tools"):
            shutil.copytree(source / component, staging / component)

        (output / "lib").mkdir(parents=True)
        subprocess.run(
            [
                sys.executable,
                str(staging / "tools" / "collect.py"),
                "--dir",
                str(staging),
                "--out",
                str(output / "lib"),
            ],
            check=True,
        )
        shutil.copytree(staging / "maps", output / "maps")

    copy_attribution(source, output)
    create_manifest(output, source_commit)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit")
    args = parser.parse_args()

    source = args.source.resolve()
    source_commit = args.source_commit
    if source_commit is None:
        source_commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        parser.error("source commit must be a 40-character lowercase Git object ID")

    build(source, args.output, source_commit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
