"""Shared portability rules for authored stable identifiers."""

from __future__ import annotations

import re


CONTENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
WINDOWS_DEVICE_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {"com{}".format(number) for number in range(1, 10)}
    | {"lpt{}".format(number) for number in range(1, 10)}
)


def is_portable_content_id(value: object) -> bool:
    """Return whether an ID is safe as both a stable key and a filename stem."""

    return (
        isinstance(value, str)
        and CONTENT_ID_RE.fullmatch(value) is not None
        and value.split(".", 1)[0] not in WINDOWS_DEVICE_BASENAMES
    )
