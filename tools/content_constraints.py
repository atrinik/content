"""Shared validation for generated authored-field constraints."""

from __future__ import annotations

from functools import lru_cache
import re
from typing import Mapping, Optional, Tuple


@lru_cache(maxsize=64)
def _compiled_pattern(expression: str) -> re.Pattern[str]:
    return re.compile(expression)


def text_constraint_violation(
    value: str, constraints: Mapping[str, object], label: str
) -> Optional[Tuple[str, str]]:
    """Return a stable diagnostic for a generated text-constraint violation."""

    minimum = constraints.get("minLength")
    maximum = constraints.get("maxLength")
    if isinstance(minimum, int) and len(value) < minimum:
        return (
            "field-below-min-length",
            "{} is shorter than {}".format(label, minimum),
        )
    if isinstance(maximum, int) and len(value) > maximum:
        return (
            "field-above-max-length",
            "{} is longer than {}".format(label, maximum),
        )
    pattern = constraints.get("pattern")
    if isinstance(pattern, str) and _compiled_pattern(pattern).fullmatch(value) is None:
        return (
            "field-pattern-mismatch",
            "{} does not match {}".format(label, pattern),
        )
    return None
