"""Inheriting columns from an ABSTRACT (non-table) base by walking the MRO.

A model can inherit columns (and its PK) from a base class that does NOT carry `@snake_model`: that
base only contributes descriptors and is NOT registered nor turned into a table. The compiler
collects the descriptors of the whole MRO (base→child), not just the class's own dictionary.
"""

from __future__ import annotations

from snakeorm import SnakeUtc, snake_datetimetz


from snakeorm.compiler import compile_model
from snakeorm.decorators import snake_model
from snakeorm.fields import SnakeColumn, snake_auto, snake_str

from snakeorm.metadata import SnakeServerDefault
from snakeorm.model import SnakeModel
from snakeorm.registry import registry


class _TimestampedBase(SnakeModel):
    """Abstract base: contributes id (auto) and created_at (server_default). NOT a table."""

    id: SnakeColumn[int] = snake_auto()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )


class _InhUser(_TimestampedBase):
    """Inherits id and created_at from the base; adds a name of its own."""

    name: SnakeColumn[str] = snake_str()


def test_child_has_inherited_and_own_columns() -> None:
    """The child ends up with the parent's columns PLUS its own."""
    table = compile_model(_InhUser)
    assert {column.name for column in table.columns} == {"id", "created_at", "name"}


def test_inherited_columns_come_before_own_in_order() -> None:
    """DDL order: the inherited ones first (id, created_at), then its own (name)."""
    table = compile_model(_InhUser)
    assert [column.name for column in table.columns] == ["id", "created_at", "name"]


def test_inherited_python_types_are_captured() -> None:
    """The Python type of an inherited column is captured from the base's annotation."""
    table = compile_model(_InhUser)
    created_at = table.get_column("created_at")
    assert created_at is not None and created_at.python_type is SnakeUtc


def test_inherited_primary_key_is_collected() -> None:
    """The inherited PK (the base's autoincrement id) is the child's primary key."""
    table = compile_model(_InhUser)
    assert [column.name for column in table.primary_key.columns] == ["id"]


class _OverrideBase(SnakeModel):
    """Base holding id and a label column whose SQL name is 'base_label'."""

    id: SnakeColumn[int] = snake_auto()
    label: SnakeColumn[str] = snake_str(name="base_label")


class _OverrideChild(_OverrideBase):
    """Redefines label under ANOTHER SQL name: the child's definition wins, with no duplicate."""

    label: SnakeColumn[str] = snake_str(name="child_label")


def test_child_override_wins_without_duplicating() -> None:
    """If the child redefines a column under the same attribute, its definition wins and nothing
    is duplicated."""
    table = compile_model(_OverrideChild)
    labels = [column for column in table.columns if column.attr_name == "label"]
    assert len(labels) == 1
    assert labels[0].name == "child_label"


class _Level1(SnakeModel):
    """Level 1 (base of the bases): the PK and nothing else."""

    id: SnakeColumn[int] = snake_auto()


class _Level2(_Level1):
    """Level 2: a base that inherits from another base and adds one column."""

    a: SnakeColumn[str] = snake_str()


class _Level3(_Level2):
    """Level 3: the concrete model; it accumulates id, a and b."""

    b: SnakeColumn[str] = snake_str()


def test_multilevel_inheritance_accumulates_all_columns() -> None:
    """A→B→C accumulates the columns of all three levels, in base→child order."""
    table = compile_model(_Level3)
    assert [column.name for column in table.columns] == ["id", "a", "b"]


class _RegBase(SnakeModel):
    """Abstract base used by a DECORATED model so the registry can be exercised."""

    id: SnakeColumn[int] = snake_auto()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )


@snake_model(table="inh_reg_users")
class _RegUser(_RegBase):
    """Decorated model inheriting from _RegBase; it adds name."""

    name: SnakeColumn[str] = snake_str()


def test_abstract_base_is_not_registered() -> None:
    """The abstract base is NOT registered nor turned into a table; only the decorated child is."""
    assert registry.table_of(_RegBase) is None
    assert registry.table_of(_RegUser) is not None


def test_registered_child_carries_inherited_columns() -> None:
    """The decorated child drags the base's columns along into its compiled table."""
    table = registry.table_of(_RegUser)
    assert table is not None
    assert [column.name for column in table.columns] == ["id", "created_at", "name"]
