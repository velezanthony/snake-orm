"""The field specifiers PER TYPE FAMILY: snake_int/snake_str/snake_decimal/snake_json.

`snake_column()` offered six type-specific knobs on EVERY column: the checker autocompleted
`max_length=` on a `SnakeColumn[int]` and `json_storage=` on a `SnakeColumn[datetime]`. That is an
illegal state that CAN be written, the exact opposite of the thesis of this project.

These specifiers are the answer, and they are no invention: they extend the pattern `snake_enum` and
`snake_auto` were already using — a dedicated specifier carrying ONLY the parameters of its family.
`snake_column()` stays for the types that take no parameters (`bool`, `date`, `UUID`, `bytes`...).
"""

from __future__ import annotations


from decimal import Decimal

import pytest

from snakeorm.compiler import compile_model
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields import (
    SNAKE_FIELD_SPECIFIERS,
    SnakeColumn,
    snake_column,
    snake_decimal,
    snake_int,
    snake_json,
    snake_str,
)
from snakeorm.metadata import SnakeIntSize, SnakeJsonStorage, SnakeServerDefault


class Product:
    """Model declaring one column of each family with its own dedicated specifier."""

    id: SnakeColumn[int] = snake_column(primary_key=True)
    stock: SnakeColumn[int] = snake_int(size=SnakeIntSize.SMALLINT)
    name: SnakeColumn[str] = snake_str(max_length=50)
    price: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)
    meta: SnakeColumn[dict] = snake_json(storage=SnakeJsonStorage.JSON)


def test_snake_int_carries_its_size() -> None:
    """`snake_int(size=...)` reaches the graph as the width of the column."""
    column = compile_model(Product).get_column("stock")
    assert column is not None
    assert column.int_size is SnakeIntSize.SMALLINT


def test_snake_str_carries_its_max_length() -> None:
    """`snake_str(max_length=...)` reaches the graph as the length of the column."""
    column = compile_model(Product).get_column("name")
    assert column is not None
    assert column.max_length == 50


def test_snake_decimal_carries_precision_and_scale() -> None:
    """`snake_decimal(precision=, scale=)` reaches the graph as the NUMERIC(p,s)."""
    column = compile_model(Product).get_column("price")
    assert column is not None
    assert (column.precision, column.scale) == (12, 2)


def test_snake_json_carries_its_storage() -> None:
    """`snake_json(storage=...)` reaches the graph as the backing store of the JSON."""
    column = compile_model(Product).get_column("meta")
    assert column is not None
    assert column.json_storage is SnakeJsonStorage.JSON


def test_defaults_match_snake_column() -> None:
    """A specifier without its knob produces the SAME thing as `snake_column()`.

    Were the defaults to diverge, moving from `snake_column()` to `snake_int()` would change the DDL
    with nobody asking for it — and the migration diff would see that as a real change.
    """

    class Plain:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        a: SnakeColumn[int] = snake_int()
        b: SnakeColumn[str] = snake_str()
        c: SnakeColumn[dict] = snake_json()

    table = compile_model(Plain)
    a, b, c = (table.get_column(n) for n in ("a", "b", "c"))
    assert a is not None and a.int_size is SnakeIntSize.BIGINT
    assert b is not None and b.max_length is None
    assert c is not None and c.json_storage is SnakeJsonStorage.JSONB


def test_shared_knobs_work_on_every_specifier() -> None:
    """Bucket A (the type-agnostic one) works the same across all four specifiers."""

    class Wide:
        id: SnakeColumn[int] = snake_int(primary_key=True)
        code: SnakeColumn[str] = snake_str(
            max_length=8, unique=True, index=True, name="codigo", db_comment="SKU"
        )
        rate: SnakeColumn[Decimal] = snake_decimal(precision=5, scale=4, default=None)
        tags: SnakeColumn[dict] = snake_json(db_comment="tags libres")

    table = compile_model(Wide)
    code = table.get_column("codigo")
    assert code is not None
    assert (code.unique, code.index, code.db_comment) == (True, True, "SKU")
    assert table.primary_key.columns[0].name == "id"
    tags = table.get_column("tags")
    assert tags is not None and tags.db_comment == "tags libres"


def test_server_default_is_available_on_typed_specifiers() -> None:
    """A typed specifier accepts `server_default` and keeps the column out of the INSERT.

    Without this a gap would be left: a column with precision AND a server-side value would have no
    way of being declared. A missing path is the very same sin as a knob too many.
    """

    class Invoice:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        total: SnakeColumn[Decimal] = snake_decimal(
            precision=10, scale=2, server_default=SnakeServerDefault.ZERO
        )

    column = compile_model(Invoice).get_column("total")
    assert column is not None
    assert column.server_default is SnakeServerDefault.ZERO
    assert column.has_server_default is True


def test_every_exported_field_specifier_is_registered_as_one() -> None:
    """EVERY `snake_*` that `snakeorm.fields` exports as a column default is in the canonical tuple.

    Missing from it, `@dataclass_transform` does not recognise the call, the checker reads it as a
    plain default value, and the generated `__init__` stops being typed IN SILENCE for every column
    declared that way. Measured on `snake_float`: `Medicion()` with the argument missing passed mypy
    with zero errors and raised `TypeError: missing required argument: 'valor'` at runtime. Silence
    from the type checker on a model that cannot be built is the exact failure this ORM exists to
    prevent.

    The previous version of this test named four specifiers by hand — the four that existed the day
    it was written — so `snake_float`, `snake_time` and `snake_timetz` were added later and nobody
    noticed. That is why the set is DERIVED from the module's exports: a list has to be remembered,
    and this one was not.

    What is deliberately excluded is what is not a column default: `snake_to_one` (a relation is not
    a constructor argument), and the table-level helpers, which return `None` or an info object
    rather than a column value. Position tells them apart, so no second list is needed.
    """
    import inspect

    from snakeorm import fields as fields_module

    table_level = {"snake_check", "snake_checks", "snake_indexes"}
    exported = {
        name: getattr(fields_module, name)
        for name in dir(fields_module)
        if name.startswith("snake_") and name not in table_level
    }
    registered = set(SNAKE_FIELD_SPECIFIERS)
    missing = sorted(
        name
        for name, specifier in exported.items()
        if inspect.isfunction(specifier) and specifier not in registered
    )

    assert missing == [], (
        f"these specifiers are exported but not in SNAKE_FIELD_SPECIFIERS: {missing}. Their "
        f"columns would not type __init__, the checker would stay silent and the constructor "
        f"would raise at runtime."
    )


def test_guard_still_fires_when_a_specifier_meets_the_wrong_type() -> None:
    """The specifier does not switch off the compiler's guard.

    The type is told by the ANNOTATION, not by the specifier: `snake_int()` over a
    `SnakeColumn[str]` is still an illegal state. The checker must reject it, and so must whoever skips the types.
    """

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        name: SnakeColumn[str] = snake_int(size=SnakeIntSize.SMALLINT)

    with pytest.raises(SnakeModelDefinitionError, match="int"):
        compile_model(Bad)
