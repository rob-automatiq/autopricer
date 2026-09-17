"""Canonicalisation of section and row labels.

The two data sources in the lake label the same seat differently:

* VividSeats listings prefix the bowl and zero-pad floor sections:
  ``"Lower Level 112"``, ``"Upper Level 228"``, ``"03"``, ``"06"``
* POS sales carry the bare section number: ``"112"``, ``"228"``, ``"06"``

Everything is reduced here to a canonical key -- the section number as a plain
string with no bowl prefix and no leading zeros -- so the two sides join.
"""

from __future__ import annotations

import re

_BOWL_PREFIX = re.compile(
    r"^(lower|upper|club|suite|main|balcony|mezzanine)\s+(level|lvl)\s+",
    re.IGNORECASE,
)

# Row labels that carry no positional meaning. Seen in the lake as placeholders
# for season-ticket packages, parking and not-yet-assigned inventory.
_NON_ROWS = {"", "TBD", "TBA", "NONE", "NULL", "GA", "PACKAGE", "ZZ"}


def section_key(raw: str | None) -> str | None:
    """Return the canonical section key, or ``None`` if it is not a seat section.

    >>> section_key("Lower Level 112")
    '112'
    >>> section_key("06")
    '6'
    >>> section_key("7th St.")        # a parking listing, not a seat
    """
    if raw is None:
        return None
    s = _BOWL_PREFIX.sub("", str(raw).strip())
    s = s.strip()
    if not s:
        return None
    # A seat section is numeric once the bowl prefix is gone. Anything else
    # ("7th St.", "Parking Lot B") is not inventory this tool prices.
    if not s.isdigit():
        return None
    key = s.lstrip("0")
    return key or None


def row_key(raw: str | None) -> str | None:
    """Return the canonical (upper-cased, trimmed) row label."""
    if raw is None:
        return None
    r = str(raw).strip().upper()
    return r or None


def row_ordinal(raw: str | None) -> int | None:
    """Return a depth ordinal for a row, or ``None`` when it has no position.

    Letter rows map ``A -> 1`` through ``Z -> 26``. Target Center uses ``I`` and
    ``O`` as real rows (sections 207, 215, 227 and 228 all have them), so the
    alphabet is *not* skipped the way some venues do.

    Several lower-bowl sections (104, 120, 124, 138) label their front rows
    numerically. A numeric row ``n`` is given ordinal ``n``, which places it at
    the same depth as the n-th letter row -- these are front rows in the
    sections that use them, so the two schemes line up.
    """
    r = row_key(raw)
    if r is None or r in _NON_ROWS:
        return None
    if r.isdigit():
        n = int(r)
        return n if 1 <= n <= 40 else None
    if len(r) == 1 and "A" <= r <= "Z":
        return ord(r) - ord("A") + 1
    return None
