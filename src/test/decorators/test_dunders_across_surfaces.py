"""BUG #16 — `__repr__`/`__eq__`/`__hash__` across ALL THREE declaration surfaces.

Task 1.6 installed them... on `@snake_model` and nowhere else. `@snake_db_first` and `@snake_view`
got the generated `__init__` and nothing more, so a mirror or a view printed
`<LogLegacy object at 0x7f...>` and two objects of the SAME row did not recognise each other as
equal.

It has the same shape as BUG #10 (the field specifier missing from `field_specifiers`): a feature
implemented on one out of N parallel surfaces. And both were uncovered the same way, not by
exercising the feature but by COMPARING siblings — that is where these things show up.

The docstring of the installer itself said that a dataclass-first ORM whose `print(user)` gave back
`<User object at 0x...>` would be a joke. For two of its three surfaces, it was.
"""

from __future__ import annotations

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeView,
    snake_db_first,
    snake_int,
    snake_model,
    snake_str,
    snake_view,
)
from snakeorm.registry import SnakeRegistry

_REG = SnakeRegistry()


@snake_model(table="dun_managed", registry=_REG)
class Managed(SnakeModel):
    """Control: the surface where this ALREADY worked."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_db_first(table="dun_mirror", registry=_REG)
class Mirror(SnakeModel):
    """Mirror WITH a PK: here equality by primary key means the same as it does above."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_db_first(table="dun_log", registry=_REG)
class LogSinPk(SnakeModel):
    """Mirror WITHOUT a PK: there is no row identity, so equality must fall back to identity."""

    source: SnakeColumn[str] = snake_str()


# `snake_view` does not accept `registry=` (an asymmetry of its own, noted elsewhere): it goes to
# the global one, which is why the name is distinctive.
@snake_view(sql="SELECT 1 AS id, 'x'::text AS name")
class VistaDunders(SnakeView):
    """A view: it is queried like any other model, so it prints like any other model."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@pytest.mark.parametrize(
    ("model", "label"),
    [(Managed, "Managed"), (Mirror, "Mirror"), (VistaDunders, "VistaDunders")],
)
def test_every_surface_prints_its_values(model: type, label: str) -> None:
    """All three surfaces print their values, not the memory address."""
    text = repr(model(id=1, name="ana"))

    assert text == f"{label}(id=1, name='ana')"
    assert "object at 0x" not in text


@pytest.mark.parametrize("model", [Managed, Mirror, VistaDunders])
def test_every_surface_compares_by_primary_key(model: type) -> None:
    """Two objects of the SAME row are equal even when one of them is stale.

    It is what makes an `in`, a `set` or an `assert x == y` usable in a test: without it, re-reading
    the same row handed you an object "different" from the one you already had.
    """
    assert model(id=1, name="ana") == model(id=1, name="ANA")
    assert model(id=1, name="ana") != model(id=2, name="ana")


def test_a_mirror_without_a_primary_key_falls_back_to_identity() -> None:
    """With no PK there is no row identity to compare, so the object's own identity rules.

    The other half of the rule, and the half that averts disaster: were it to reason "all empty PKs
    are equal", a `set` of a hundred log lines would collapse into one.
    """
    first, second = LogSinPk(source="cron"), LogSinPk(source="cron")

    assert first != second
    assert first == first
    assert len({first, second}) == 2
