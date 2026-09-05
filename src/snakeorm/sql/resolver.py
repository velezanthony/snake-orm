"""What the SQL emitter needs from a registry: resolving a relationship to its target.

A Protocol and not `SnakeRegistry` itself, for the reason the whole `sql/` package exists: emitting
must not depend on the thing that stores models, only on the one question it has to ask. It also
keeps the tests honest — a double can answer this without standing up a registry, which is what lets
the negative test re-run the OLD resolution and demand the wrong answer.
"""

from __future__ import annotations

from typing import Protocol

from snakeorm.metadata import SnakeRelationshipInfo, SnakeTableInfo


class SnakeRelationshipResolver(Protocol):
    """Answers WHERE a relationship points, unambiguously."""

    def resolve_relationship(
        self, relationship: SnakeRelationshipInfo
    ) -> tuple[SnakeTableInfo | None, type | None]:
        """The target's `(table, class)`, preferring the qualified name over the class name.

        The class name is NOT unique —two apps can each declare a `Customer`— and the index keyed by
        it is kept by whichever registered last. The qualified name is protected by the collision
        guard, which is why it is the one that answers.
        """
        ...
