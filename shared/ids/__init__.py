"""Opaque identifiers. Domain prefixes are chosen by each domain."""
import re
from uuid import uuid4


def new_id(prefix: str) -> str:
    if not re.fullmatch(r"[A-Z][A-Z0-9-]*", prefix):
        raise ValueError("Invalid ID prefix")
    return f"{prefix}-{uuid4().hex}"
