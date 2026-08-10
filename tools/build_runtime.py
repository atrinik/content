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


REVIEW_ONLY_MAP_ENTRIES = {"light-source-evidence", "light-source-review.json"}


def review_only_map_entries(directory: str, names: list[str], map_root: Path) -> set[str]:
    """Return review-only root entries excluded from playable runtime maps."""

    if Path(directory) == map_root:
        return set(names) & REVIEW_ONLY_MAP_ENTRIES
    return set()


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


def load_release_contract(source: Path) -> dict[str, object]:
    path = source / "contracts" / "release-lines" / "classic-1x.json"
    contract = json.loads(path.read_text(encoding="utf-8"))
    if (
        contract.get("schema_version") != 1
        or contract.get("repository") != "atrinik/content"
        or contract.get("branch") != "1.x"
        or contract.get("replacement_ready") is not False
        or contract.get("replacement_toolkit_package") is not False
    ):
        raise ValueError("classic 1.x release contract is invalid")
    consumers = contract.get("consumers")
    if consumers != ["classic/client", "classic/editor", "classic/server"]:
        raise ValueError("classic 1.x consumer contract is invalid")
    return contract


def create_manifest(
    output: Path,
    source_commit: str,
    source_branch: str,
    release_version: str,
    release_contract: dict[str, object],
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
    manifest = {
        "schema_version": 2,
        "source": {
            "repository": release_contract["repository"],
            "branch": source_branch,
            "commit": source_commit,
        },
        "release_line": "1.x",
        "release_version": release_version,
        "content_format": release_contract["content_format"],
        "artifact_format": release_contract["artifact_format"],
        "compatible_classic_releases": release_contract["compatible_classic_releases"],
        "consumers": release_contract["consumers"],
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
    source_branch: str = "1.x",
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
    release_contract = load_release_contract(source)
    if source_branch != release_contract["branch"]:
        raise ValueError("runtime branch does not match the classic release contract")
    if release_version != "unreleased" and re.fullmatch(r"1\.[0-9]+\.[0-9]+", release_version) is None:
        raise ValueError("classic runtime release version must satisfy 1.x")
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
        shutil.copyfile(
            source / "contracts" / "release-lines" / "classic-1x.json",
            candidate / "compatibility.json",
        )
        create_manifest(
            candidate,
            source_commit,
            source_branch,
            release_version,
            release_contract,
        )

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
    parser.add_argument("--source-branch", default="1.x", choices=("1.x",))
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

    build(
        source,
        args.output,
        source_commit,
        args.source_branch,
        args.release_version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
