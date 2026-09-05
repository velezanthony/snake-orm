"""Framework-agnostic DTOs: they turn a SnakeORM model into a JSON-able `dict`, once and for all.

The blog is the SHOWCASE (native per-framework serializers + OpenAPI). The remaining six domains
expose plain JSON through these shared DTOs: that way they get exercised and show up in the debug
panel WITHOUT tripling the schema/serializer boilerplate in every framework. Each endpoint calls its
use case and serializes with these functions; secrets (e.g. the token value) are NEVER emitted.
"""

from __future__ import annotations

from datetime import datetime


def iso(value: datetime) -> str:
    """Serializes a `datetime` to ISO 8601 (the DTOs emit no objects, only JSON-able primitives)."""
    return value.isoformat()
