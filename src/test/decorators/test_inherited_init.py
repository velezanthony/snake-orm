"""The child's generated __init__ includes the fields INHERITED from an abstract base.

`_make_init` walks the MRO: inherited required fields are demanded exactly like the own ones,
inherited ones carrying a default get filled in, and the ones the DB provides (auto,
server_default) are left out.
"""

from __future__ import annotations

from snakeorm import SnakeUtc, snake_datetimetz

from datetime import datetime

import pytest

from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, snake_auto, snake_str

from snakeorm.metadata import SnakeServerDefault
from snakeorm.model import SnakeModel


class _Base(SnakeModel):
    """Abstract base: id (auto), created_at (server_default), owner (required), tag (default)."""

    id: SnakeColumn[int] = snake_auto()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )
    owner: SnakeColumn[str] = snake_str()
    tag: SnakeColumn[str] = snake_str(default="libre")


@snake_model(table="inh_init_users")
class _User(_Base):
    """Inherits everything from _Base; adds name (its own, required)."""

    name: SnakeColumn[str] = snake_str()


def test_init_assigns_inherited_and_own_required_fields() -> None:
    """__init__ assigns an inherited required field (owner) and an own one (name)."""
    user = _User(name="documento", owner="ana")
    assert user.name == "documento"
    assert user.owner == "ana"


def test_init_requires_inherited_required_field() -> None:
    """A missing inherited required field (owner) ⇒ TypeError, just like a missing own one."""
    with pytest.raises(TypeError):
        _User(name="documento")  # type: ignore[call-arg]  # owner is missing (inherited)


def test_inherited_literal_default_is_applied() -> None:
    """An inherited field with a literal default is filled in when it is not passed."""
    user = _User(name="documento", owner="ana")
    assert user.tag == "libre"


def test_inherited_auto_pk_is_not_a_constructor_argument() -> None:
    """id (autoincrement, inherited) is no constructor argument: the DB provides it."""
    with pytest.raises(TypeError):
        _User(name="documento", owner="ana", id=5)  # type: ignore[call-arg]


def test_inherited_server_default_is_not_a_constructor_argument() -> None:
    """created_at (server_default, inherited) is no constructor argument: the DB provides it."""
    with pytest.raises(TypeError):
        _User(name="documento", owner="ana", created_at=datetime.now())  # type: ignore[call-arg]
