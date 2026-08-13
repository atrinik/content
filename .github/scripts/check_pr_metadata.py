#!/usr/bin/env python3
"""Validate pull-request metadata that becomes Semantic Release input."""

from __future__ import annotations

import os
import re
import sys


TITLE_PATTERN = re.compile(
    r"^[a-z][a-z0-9-]*(\([a-z0-9][a-z0-9._/-]*\))?(!)?: .+"
)
CROSS_REPOSITORY_SHORTHAND = re.compile(
    r"(?<![\w/])([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#([1-9][0-9]*)"
)
CLOSING_LINE = re.compile(
    r"^[ \t]*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?[ \t]+",
    re.IGNORECASE,
)


def validation_errors(title: str, body: str) -> list[str]:
    """Return deterministic policy errors for a pull-request title and body."""

    errors: list[str] = []
    if not TITLE_PATTERN.fullmatch(title):
        errors.append(
            "PR title must use Conventional Commits style: "
            "type(scope)!: concise description"
        )

    for match in CROSS_REPOSITORY_SHORTHAND.finditer(title):
        errors.append(
            "PR title uses ambiguous cross-repository reference {}; use a full "
            "issue URL in the PR body instead".format(match.group(0))
        )

    for line_number, line in enumerate(body.splitlines(), start=1):
        closing_line = CLOSING_LINE.match(line) is not None
        for match in CROSS_REPOSITORY_SHORTHAND.finditer(line):
            if closing_line:
                continue
            reference = match.group(0)
            errors.append(
                "PR body line {} uses ambiguous nonclosing reference {}; "
                "use a full https://github.com/OWNER/REPOSITORY/issues/NUMBER "
                "URL instead".format(line_number, reference)
            )
    return errors


def main() -> int:
    errors = validation_errors(
        os.environ.get("PR_TITLE", ""),
        os.environ.get("PR_BODY", ""),
    )
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
