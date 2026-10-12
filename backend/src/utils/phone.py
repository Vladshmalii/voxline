"""Phone number normalization.

One representation everywhere — ``+`` and digits — because the client table
dedupes on the phone column: two spellings of one number must collide, not
create two clients that both get dialed.
"""

from __future__ import annotations

import re

_JUNK = re.compile(r"[\s\-().]")
_DIALABLE = re.compile(r"\+?\d{7,15}")


def normalize_phone(raw: str) -> str:
    """Normalize a phone number to ``+<digits>`` (E.164 shape, not validated
    against numbering plans).

    Args:
        raw: The number as uploaded or typed.

    Returns:
        The normalized number.

    Raises:
        ValueError: If what remains is not a dialable number.
    """
    cleaned = _JUNK.sub("", raw.strip())
    if not _DIALABLE.fullmatch(cleaned):
        raise ValueError(f"not a dialable phone number: {raw!r}")
    return "+" + cleaned.lstrip("+")
