#!/usr/bin/env python3
"""Build an isolated, digest-addressed Atrinik runtime content tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


REVIEW_ONLY_MAP_ENTRIES = {"light-source-review.json"}


def review_only_map_entries(directory: str, names: list[str], map_root: Path) -> set[str]:
    """Return review-only and generated entries excluded from runtime maps."""

    ignored = {
        name for name in names
        if name == "__pycache__" or name.endswith(".pyc")
    }
    if Path(directory) == map_root:
        ignored.update(set(names) & REVIEW_ONLY_MAP_ENTRIES)
    return ignored


def validate_source_tree(source: Path) -> None:
    """Reject missing roots, links, and special files before staging content."""

    for component in ("arch", "maps", "tools"):
        root = source / component
        if root.is_symlink() or not root.is_dir():
            raise ValueError(
                "required source directory is missing or unsafe: {}".format(component)
            )

        def handle_walk_error(error: OSError) -> None:
            raise error

        for directory, dirnames, filenames in os.walk(
            root, followlinks=False, onerror=handle_walk_error
        ):
            dirnames.sort()
            filenames.sort()
            directory_path = Path(directory)
            for name in dirnames:
                path = directory_path / name
                if path.is_symlink():
                    raise ValueError(
                        "symbolic links are not allowed: {}".format(
                            path.relative_to(source)
                        )
                    )
            for name in filenames:
                path = directory_path / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError(
                        "links and special files are not allowed: {}".format(
                            path.relative_to(source)
                        )
                    )


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
    output = output.absolute()
    if output.is_symlink():
        raise ValueError("output must not be a symbolic link")
    output = output.resolve()
    build_root = source / "build"
    filesystem_root = Path(output.anchor)
    if output == filesystem_root or output == source or output in source.parents or (
        source in output.parents
        and output != build_root
        and build_root not in output.parents
    ):
        raise ValueError("output must not replace an authored source directory")
    if output.exists() and not output.is_dir():
        raise ValueError("output must be a directory")
    validate_source_tree(source)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".{}-build-".format(output.name), dir=output.parent
    ) as transaction_directory:
        transaction = Path(transaction_directory)
        candidate = transaction / "candidate"
        with tempfile.TemporaryDirectory(prefix="atrinik-content-") as temporary:
            staging = Path(temporary)
            for component in ("arch", "maps", "tools"):
                shutil.copytree(source / component, staging / component)

            (candidate / "lib").mkdir(parents=True)
            subprocess.run(
                [
                    sys.executable,
                    str(staging / "tools" / "collect.py"),
                    "--dir",
                    str(staging),
                    "--out",
                    str(candidate / "lib"),
                ],
                check=True,
            )
            shutil.copytree(
                staging / "maps",
                candidate / "maps",
                ignore=lambda directory, names: review_only_map_entries(
                    directory, names, staging / "maps"
                ),
            )

        copy_attribution(source, candidate)
        create_manifest(candidate, source_commit)

        previous = transaction / "previous"
        if output.exists():
            output.rename(previous)
        try:
            candidate.rename(output)
        except BaseException:
            if previous.exists():
                previous.rename(output)
            raise


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
