"""`db.query.summary`: the short shape of a statement, which is what NAMES the span.

The convention is explicit that the span name is the summary and NOT the query text. Jaeger gives
`db.query.text` no special formatting, so a span named after the whole SQL is an unreadable row; a
span named `SELECT orders` reads at a glance and groups with its five hundred siblings.

It is a HEURISTIC over already-emitted SQL, not a parser, and it says so: the verb is the first word
and the collection is the first table the statement names. Anything it cannot read comes back empty,
never wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The first word: the verb (SELECT, INSERT, CREATE...). Anything else gives no operation.
_OPERATION = re.compile(r"^\s*([A-Za-z]+)")

# The first table the statement names, however the engine quotes it (`"x"`, `` `x` ``, bare), and
# QUALIFIED or not. The optional first group is the schema: SnakeORM emits `"public"."users"` against
# Postgres, so a pattern that stopped at the first identifier named the SCHEMA on every single span.
_COLLECTION = re.compile(
    r"\b(?:FROM|INTO|UPDATE|TABLE|VIEW|INDEX)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
    r'(?:["`]?([A-Za-z_]\w*)["`]?\.)?["`]?([A-Za-z_]\w*)',
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QuerySummary:
    """A statement's `db.operation.name`, `db.collection.name` and `db.namespace`, plus the summary.

    The namespace is the SCHEMA half of a qualified name (`"public"."users"`). It is kept apart
    because the convention keeps it apart, and because folding it in made every span of a real
    request read `SELECT public`.
    """

    operation: str
    collection: str
    namespace: str = ""

    @property
    def text(self) -> str:
        """`db.query.summary`: `SELECT orders`, or the verb alone when no table is named."""
        if not self.collection:
            return self.operation
        return f"{self.operation} {self.collection}"


def summarise(sql: str) -> QuerySummary:
    """The verb and the table of an emitted statement. Empty pieces when it cannot tell."""
    operation = _OPERATION.match(sql)
    collection = _COLLECTION.search(sql)
    return QuerySummary(
        operation="" if operation is None else operation.group(1).upper(),
        collection="" if collection is None else collection.group(2),
        namespace="" if collection is None else (collection.group(1) or ""),
    )
