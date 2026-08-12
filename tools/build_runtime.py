#!/usr/bin/env python3
"""Build an isolated, digest-addressed Atrinik runtime content tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePath
import re
import shutil
import subprocess
import sys
import tempfile

REVIEW_ONLY_MAP_ENTRIES = {
    "light-source-fixture-contract.json",
    "light-source-review.json",
}
RUNTIME_SOURCE_COMPONENTS = ("arch", "maps", "tools", "contracts", "schemas")
CLASSIC_TARGET = "classic"


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

    for component in RUNTIME_SOURCE_COMPONENTS:
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


def load_target_contract(source: Path, target: str) -> dict[str, object]:
    """Load and strictly validate a supported derived-runtime target."""

    if target != CLASSIC_TARGET:
        raise ValueError("unsupported runtime target: {}".format(target))
    path = source / "contracts" / "release-lines" / "classic-main.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": 1,
        "target": CLASSIC_TARGET,
        "component": "content",
        "repository": "atrinik/content",
        "branch": "main",
        "content_format": "classic-ads-v1",
        "artifact_format": "atrinik-classic-runtime-content-v1",
        "compatible_classic_releases": ">=5.10.1 <6.0.0",
        "consumers": ["classic/client", "classic/editor", "classic/server"],
        "replacement_ready": False,
        "replacement_toolkit_package": False,
    }
    if contract != expected:
        raise ValueError("classic main target contract is invalid")
    return contract


def create_manifest(
    output: Path,
    source_commit: str,
    target_contract: dict[str, object] | None = None,
    release_version: str = "unreleased",
) -> None:
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
    if target_contract is None:
        manifest = {
            "schema_version": 1,
            "source_commit": source_commit,
            "files": files,
        }
    else:
        manifest = {
            "schema_version": 2,
            "target": target_contract["target"],
            "source": {
                "repository": target_contract["repository"],
                "branch": target_contract["branch"],
                "commit": source_commit,
            },
            "release_version": release_version,
            "content_format": target_contract["content_format"],
            "artifact_format": target_contract["artifact_format"],
            "compatible_classic_releases":
                target_contract["compatible_classic_releases"],
            "consumers": target_contract["consumers"],
            "replacement_ready": False,
            "replacement_toolkit_package": False,
            "license_files": [
                entry for entry in files
                if entry["path"].startswith("attribution/")
                and PurePath(entry["path"]).name in {"COPYING", "LICENSE"}
            ],
            "files": files,
        }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def build(
    source: Path,
    output: Path,
    source_commit: str,
    target: str | None = None,
    release_version: str = "unreleased",
) -> None:
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
    target_contract = (
        load_target_contract(source, target) if target is not None else None
    )
    if (
        target_contract is not None
        and release_version != "unreleased"
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release_version) is None
    ):
        raise ValueError("classic runtime release version must be semantic")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix=".{}-build-".format(output.name), dir=output.parent
    ) as transaction_directory:
        transaction = Path(transaction_directory)
        candidate = transaction / "candidate"
        with tempfile.TemporaryDirectory(prefix="atrinik-content-") as temporary:
            staging = Path(temporary)
            for component in RUNTIME_SOURCE_COMPONENTS:
                component_source = source / component
                if component_source.is_dir():
                    shutil.copytree(component_source, staging / component)

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
        if target_contract is not None:
            shutil.copyfile(
                source / "contracts" / "release-lines" / "classic-main.json",
                candidate / "compatibility.json",
            )
        create_manifest(candidate, source_commit, target_contract, release_version)

        previous = transaction / "previous"
        if output.exists():
            output.rename(previous)
        try:
            candidate.rename(output)
        except BaseException:
            if previous.exists():
                previous.rename(output)
            raise


def validate_classic_source_coordinate(source: Path, source_commit: str) -> None:
    """Require a clean checkout at the exact commit named by the manifest."""

    actual_commit = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_commit != source_commit:
        raise ValueError("source commit does not match the checked-out content")
    dirty = subprocess.run(
        ["git", "-C", str(source), "status", "--porcelain", "--untracked-files=normal"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if dirty:
        raise ValueError("classic target requires a clean source checkout")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit")
    parser.add_argument("--target", choices=(CLASSIC_TARGET,))
    parser.add_argument("--release-version", default="unreleased")
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

    if args.target is not None:
        try:
            validate_classic_source_coordinate(source, source_commit)
        except ValueError as error:
            parser.error(str(error))

    build(
        source,
        args.output,
        source_commit,
        args.target,
        args.release_version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
