"""Validate conventional pull-request titles and the 1.x release boundary."""

from __future__ import annotations

import argparse
import re
import sys


TITLE_PATTERN = re.compile(
    r"^(?P<type>[a-z][a-z0-9-]*)"
    r"(?:\([a-z0-9][a-z0-9._/-]*\))?"
    r"(?P<breaking>!)?: .+"
)


def validation_error(base: str, title: str) -> str | None:
    """Return the policy failure for *title*, or ``None`` when it is valid."""

    match = TITLE_PATTERN.fullmatch(title)
    if match is None:
        return (
            "PR title must use Conventional Commits style: "
            "type(scope)!: concise description"
        )
    if base == "1.x" and (
        match.group("type") == "feat" or match.group("breaking") is not None
    ):
        return (
            "1.x accepts patch releases only; feature and breaking pull-request "
            "titles must target main"
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("title")
    arguments = parser.parse_args()
    error = validation_error(arguments.base, arguments.title)
    if error is not None:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
