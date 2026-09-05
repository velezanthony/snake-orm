"""What CARDINALITY a relationship has: one, many, or many through a bridge."""

from __future__ import annotations

from enum import Enum


class SnakeRelationshipKind(Enum):
    """Cardinality of a relationship. An enum, not a `Literal[...]` of strings, on purpose.

    A `Literal` protects assignment but NOT comparison, and every use of the field is a comparison
    (`rel.kind == "to_onee"` compiles clean in both checkers and switches off a branch without
    warning: a JOIN that never gets emitted, an FK that never gets created). The enum makes the typo
    unwritable. Same decision as `SnakeTableKind`.

    - `TO_ONE`: FK. This model points to ONE on the other side.
    - `TO_MANY`: the inverse. N on the other side point here.
    - `TO_MANY_THROUGH`: many-to-many via a DECLARED bridge model.
    """

    TO_ONE = "to_one"
    TO_MANY = "to_many"
    TO_MANY_THROUGH = "to_many_through"

    @classmethod
    def coerce(cls, value: object) -> SnakeRelationshipKind:
        """Accepts the enum, or the string carried by already-generated history.

        Old migrations carry the literal string (`"to_one"`) and are immutable; without converting,
        `is` comparisons would return `False` (the very silent failure the enum came to kill off).
        An unknown value blows up HERE, not twelve branches later.
        """
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError:
                pass
        valid = ", ".join(repr(member.value) for member in cls)
        raise ValueError(
            f"Invalid relationship cardinality: {value!r}. The available ones are: {valid}."
        )
