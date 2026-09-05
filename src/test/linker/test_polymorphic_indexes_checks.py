"""Indexes and CHECKs declared on a polymorphic CHILD must be lifted to the physical table (the base).

Polymorphic inheritance uses ONE single table: `Dog` and `Cat` live in `animales`. The linker was
already lifting the child COLUMNS to the base (or the `CREATE TABLE` would come out without them),
but not the indexes nor the CHECKs the child declared over those columns. Result: the DB was left
without the `chip` index and without the `color` enum CHECK, silently —exactly what this project
promises does NOT happen—.

The discriminator is an edge case: the child inherits it and indexes it, and the base already has
that index. It is deduplicated by resolved name (both against the SAME physical table), no dupes.
"""

from __future__ import annotations

from enum import StrEnum

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    snake_discriminator,
    snake_int,
    snake_link,
    snake_model,
    snake_str,
)
from snakeorm.dialects import PostgresDialect
from snakeorm.fields import snake_enum
from snakeorm.migration import emit_create_table
from snakeorm.registry import SnakeRegistry


class _Color(StrEnum):
    NEGRO = "negro"
    MARRON = "marron"


def _grafo() -> SnakeRegistry:
    """Base `Animal` + child `Dog` with an index and an enum of their own, already linked."""
    reg = SnakeRegistry()

    @snake_model(table="poly_animales", registry=reg)
    class Animal(SnakeModel):
        id: SnakeColumn[int] = snake_int(primary_key=True)
        kind: SnakeColumn[str] = snake_discriminator()

    @snake_model(discriminator_value="dog", registry=reg)
    class Dog(Animal):
        chip: SnakeColumn[str | None] = snake_str(index=True)
        color: SnakeColumn[_Color | None] = snake_enum(_Color)

    snake_link(reg)
    reg._animal = Animal  # type: ignore[attr-defined]  # to recover it in the test
    return reg


def test_the_childs_index_reaches_the_base_table() -> None:
    """Checks that the `chip` index (declared on the child) reaches the physical base table."""
    reg = _grafo()
    table = reg.table_of(reg._animal)  # type: ignore[attr-defined]
    assert table is not None
    names = {i.resolved_name(table.name) for i in table.indexes}
    assert "ix_poly_animales_chip" in names


def test_the_childs_enum_check_reaches_the_ddl() -> None:
    """Checks that the `color` enum CHECK (declared on the child) shows up in the base CREATE TABLE."""
    reg = _grafo()
    table = reg.table_of(reg._animal)  # type: ignore[attr-defined]
    assert table is not None
    ddl = emit_create_table(table, PostgresDialect())
    assert 'CHECK ("color" IN (' in ddl


def test_the_inherited_discriminator_index_is_not_duplicated() -> None:
    """Checks the dedup: the discriminator index, shared by child and base, appears ONCE."""
    reg = _grafo()
    table = reg.table_of(reg._animal)  # type: ignore[attr-defined]
    assert table is not None
    names = [i.resolved_name(table.name) for i in table.indexes]
    assert names.count("ix_poly_animales_kind") == 1
