"""Identifiers and canonical strings.

Authored rows get time-ordered UUIDs so B-tree inserts stay sequential.
Derived rows get a sha256 of their natural key so reloads are idempotent and
references survive an engine move (SDD section 5).
"""

import datetime as dt
import hashlib
import uuid

_SEP = "\x1f"  # Unit separator; rejected inside a natural-key part.
_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def new_id() -> str:
    """Returns a UUIDv7 as a 36-character string.

    Returns:
        The canonical hyphenated form.
    """
    return str(uuid.uuid7())


def row_id(*parts: object) -> str:
    """Returns a deterministic id for the parts of a natural key.

    Args:
        *parts: The natural-key columns, in schema order. None hashes as the
            empty string so a nullable key column still hashes stably.

    Returns:
        A 64-character hex sha256.

    Raises:
        ValueError: If a part contains the unit separator, which would make
            two different keys hash alike.
    """
    texts = ["" if p is None else str(p) for p in parts]
    if any(_SEP in text for text in texts):
        raise ValueError("natural-key part contains the unit separator")
    return hashlib.sha256(_SEP.join(texts).encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Returns the hex sha256 of raw bytes (content addressing).

    Args:
        data: The bytes to hash.

    Returns:
        A 64-character hex sha256.
    """
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    """Returns the UTC time in the format the schema checks accept.

    Returns:
        The time as YYYY-MM-DDTHH:MM:SSZ.
    """
    return dt.datetime.now(dt.UTC).strftime(_ISO_FORMAT)


def dimensions_key(dimensions: dict[str, str] | None) -> str:
    """Returns the canonical 'axis=member;axis=member' string, sorted by axis.

    Axis and member are stripped of surrounding whitespace before sorting, so
    two spellings of one context give one key.

    Args:
        dimensions: XBRL axis qname to member qname, or None.

    Returns:
        The canonical string; the empty string when there are no dimensions.

    Raises:
        ValueError: If an axis or member is empty or contains '=' or ';'.
    """
    if not dimensions:
        return ""
    pairs: dict[str, str] = {}
    for raw_axis, raw_member in dimensions.items():
        axis, member = raw_axis.strip(), raw_member.strip()
        for part in (axis, member):
            if not part or "=" in part or ";" in part:
                raise ValueError(f"bad dimension part {part!r}")
        if axis in pairs:
            raise ValueError(f"axis {axis!r} given twice")
        pairs[axis] = member
    return ";".join(f"{axis}={pairs[axis]}" for axis in sorted(pairs))
