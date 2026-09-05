"""The Model Compiler: Python class -> immutable SnakeTableInfo.

It walks the descriptors ONCE. The type comes from the annotation; `nullable` is inferred
from `| None`; the primary key (primary_key=True columns) is mandatory.
"""

from __future__ import annotations

import inspect
import sys
from dataclasses import MISSING as _NO_DEFAULT
from dataclasses import Field, fields
from datetime import datetime
from enum import Enum
from typing import Any, get_args, get_type_hints

from snakeorm.helpers.annotations import unwrap_optional
from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.expressions import SnakeExpr
from snakeorm.fields import MISSING, SnakeColumn
from snakeorm.helpers.inheritance import collect_inherited
from snakeorm.times import SnakeUtc
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeDateTimeParams,
    SnakeEnumStorage,
    SnakeIndexInfo,
    SnakePolymorphicInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
    SnakeTableKind,
)


def _column_hints(cls: type) -> dict[str, Any]:
    """Resolves annotations, tolerating forward refs of relations to models not yet defined.

    `get_type_hints` is all-or-nothing: a `SnakeToMany[Child]` pointing at a model further down blows
    it up. Since the compiler only cares about COLUMNS, on failure it resolves those alone (the linker
    resolves the relations afterwards).
    """
    try:
        return get_type_hints(cls)
    except NameError:
        # Fallback walking the MRO: each class resolves ITS OWN column annotations with its
        # module's globals (so an abstract base from another module contributes its columns too).
        resolved: dict[str, Any] = {}
        for klass in reversed(cls.__mro__):
            globalns = getattr(sys.modules.get(klass.__module__), "__dict__", {})
            # `inspect.get_annotations` and NOT `vars(klass)["__annotations__"]`: since 3.14 (PEP
            # 649) annotations are lazy and no longer sit in the class `__dict__`, so the raw read
            # answered an EMPTY dict there and every column fell through to `object`.
            for attr, raw in inspect.get_annotations(klass).items():
                if not isinstance(vars(klass).get(attr), SnakeColumn):
                    continue
                resolved[attr] = eval(raw, globalns) if isinstance(raw, str) else raw  # noqa: S307
        return resolved


def _compile_indexes(
    cls: type, columns: list[SnakeColumnInfo]
) -> tuple[SnakeIndexInfo, ...]:
    """The table's indexes: those declared in `SnakeIndexes` plus those from the `index=True` flag.

    The flag produces a NON-unique index. The explicit declaration wins: if `SnakeIndexes` already
    covers those columns, the flag does not duplicate. It goes by the SQL name, not the attribute's.
    """
    declared = [
        SnakeIndexInfo(
            columns=index.column_names(),
            unique=index.unique,
            name=index.name,
            where=index.where,
            method=index.method,
        )
        for index in getattr(cls, "SnakeIndexes", [])
    ]
    covered = {index.columns for index in declared}
    from_flag = [
        SnakeIndexInfo(columns=(column.name,))
        for column in columns
        if column.index and (column.name,) not in covered
    ]
    return (*declared, *from_flag)


def _guard_enum_declaration(
    cls: type, attr: str, python_type: type, descriptor: SnakeColumn[Any]
) -> None:
    """Demands `snake_enum` when the annotation is an Enum. One single path, and an explicit one.

    Without the guard the failure arrived late: the dialect blew up while generating the DDL, and the
    return journey would hand back the raw `str` instead of the member (breaking the declared type).
    """
    if not (isinstance(python_type, type) and issubclass(python_type, Enum)):
        return
    if descriptor.enum_type is None:
        raise SnakeModelDefinitionError(
            f"{cls.__name__}.{attr} is annotated as {python_type.__name__}, which is an "
            f"enum, but it was declared with snake_column(). Use "
            f"snake_enum({python_type.__name__}) to decide how it gets stored."
        )


def _guard_type_params(
    cls: type, attr: str, python_type: type, descriptor: SnakeColumn[Any]
) -> None:
    """Rejects one family's parameters on a column of ANOTHER family.

    ONE guard for all four (and for the fifth that gets added): the family knows which Python type it
    belongs to (`params.python_type`), so comparing that against the annotation is enough. There used
    to be a hand-written guard per knob — and that is why `precision`/`scale` went without one for the
    project's entire life: nobody remembered to write the fourth.

    It fails AT COMPILE TIME, in our own words. Without this, `precision` on a `str` did not blow up
    until the `migrate`, with a raw syntax error from the engine.
    """
    params = descriptor.type_params
    if params is None or params.accepts(python_type):
        return
    expected = params.python_type.__name__
    # What the USER wrote, falling back to the family's own name. The message used to take the
    # declarator from the FAMILY always, so `snake_auto()` was reported as `snake_int()` and
    # `snake_datetimetz()` as `snake_datetime()` — naming a call that does not appear in the file
    # being complained about, in the best-designed guard of the compiler.
    declarator = descriptor.declared_by or params.declarator
    # And only the parameters that DIFFER from their default. Listing everything that was not `None`
    # included the ones sitting untouched, so `snake_auto()` — which takes no size — was reported as
    # "declares size=BIGINT" and sent the reader hunting for a `size=` they never typed.
    explicit = ", ".join(
        f"{field.name}={getattr(params, field.name)}"
        for field in fields(params)
        if getattr(params, field.name) is not None
        and getattr(params, field.name) != _default_of(field)
    )
    # With nothing set explicitly there is no parameter to quote, and "declares type parameters" is
    # not a sentence anybody wants to read: the specifier itself is the whole complaint.
    said = (
        f"declares {explicit} with {declarator}()"
        if explicit
        else f"is declared with {declarator}()"
    )
    raise SnakeModelDefinitionError(
        f"{cls.__name__}.{attr} {said}, which only "
        f"applies to a {expected} column, but its type is "
        f"{getattr(python_type, '__name__', python_type)!r}. The ANNOTATION is what rules the "
        f"type: either change it to {expected}, or declare the column with the specifier of its "
        f"family."
    )


def _default_of(field: Field[object]) -> object:
    """The default a dataclass field carries, or a sentinel that equals nothing.

    `MISSING` here is `dataclasses.MISSING`, and it is imported under another name on purpose: this
    module already imports a `MISSING` from `snakeorm.fields`, and the two are different sentinels.
    """
    if field.default is not _NO_DEFAULT:
        return field.default
    if field.default_factory is not _NO_DEFAULT:
        return field.default_factory()
    return _NO_DEFAULT


def _guard_datetime_declaration(
    cls: type, attr: str, python_type: type, descriptor: SnakeColumn[Any]
) -> None:
    """Demands that the date specifier and the annotation say the SAME thing about the zone.

    `TIMESTAMP` and `TIMESTAMPTZ` are different database types, so the model has to say which one it
    creates — just as `snake_int(size=SMALLINT)` says SMALLINT — and the specifier is where that is
    read. The Python type says it too, but covering something else: `SnakeUtc` is what makes building
    a non-UTC value impossible, and the checker is what enforces that. Each covers what the other
    does not.

    Redundancy is only healthy if it cannot lie, and that is what this guard is about. Same treatment
    as `snake_enum(Status)` over a `SnakeColumn[Status]`: it is repeated, and it is checked.

    A date declared with `snake_column()` is AMBIGUOUS and is rejected too: choosing on the user's
    behalf is exactly what made EVERYTHING `TIMESTAMPTZ` without anyone having decided it.
    """
    if not (isinstance(python_type, type) and issubclass(python_type, datetime)):
        return
    params = descriptor.type_params
    if not isinstance(params, SnakeDateTimeParams):
        raise SnakeModelDefinitionError(
            f"{cls.__name__}.{attr} is a date declared with snake_column(), and that does not say "
            f"which column to create. Use snake_datetimetz() with SnakeColumn[SnakeUtc] if it "
            f"stores an INSTANT (TIMESTAMPTZ), or snake_datetime() with SnakeColumn[datetime] if "
            f"it stores a WALL-CLOCK TIME (TIMESTAMP), which does not identify any instant."
        )
    with_zone = python_type is SnakeUtc
    if params.tz == with_zone:
        return
    if params.tz:
        raise SnakeModelDefinitionError(
            f"{cls.__name__}.{attr} uses snake_datetimetz() (a TIMESTAMPTZ column, an instant) "
            f"but is annotated {python_type.__name__}, which is a wall-clock time and does not "
            f"identify one. Annotate it SnakeColumn[SnakeUtc], or declare it with snake_datetime()."
        )
    raise SnakeModelDefinitionError(
        f"{cls.__name__}.{attr} is annotated SnakeUtc (an instant) but uses snake_datetime(), "
        f"which creates a TIMESTAMP without a zone: storing it there would lose the tzinfo and with "
        f"it the instant. Declare it with snake_datetimetz(), or annotate it SnakeColumn[datetime] "
        f"if it is a wall-clock time."
    )


def _enum_checks(columns: list[SnakeColumnInfo]) -> tuple[SnakeCheckInfo, ...]:
    """CHECKs derived from the enum columns with `storage=CHECK`.

    The rule is DERIVED from the enum's members (adding a value changes the CHECK and the diff spots
    it). The values go in the enum's order, so the SQL is stable between runs.
    """
    checks: list[SnakeCheckInfo] = []
    for column in columns:
        if (
            column.enum_type is None
            or column.enum_storage is not SnakeEnumStorage.CHECK
        ):
            continue
        allowed = tuple(member.value for member in column.enum_type)
        expression: SnakeExpr[Any] = SnakeExpr(
            path=(column.name,), python_type=column.python_type
        )
        checks.append(SnakeCheckInfo(condition=expression.in_(allowed)))
    return tuple(checks)


def compile_model(
    cls: type,
    *,
    table: str | None = None,
    prefix: str | None = None,
    schema: str = DEFAULT_SCHEMA,
    database: str = "default",
    kind: SnakeTableKind = SnakeTableKind.TABLE,
    polymorphic: SnakePolymorphicInfo | None = None,
) -> SnakeTableInfo:
    """Compiles a class with SnakeColumn descriptors into an immutable SnakeTableInfo.

    Table name `{prefix}_{table}`; `table` changes only the table, `prefix` the namespace. With
    `kind=VIEW` (`@snake_view`) it shares the pipeline but does NOT demand a PK; the decorator adds
    the SELECT afterwards (`view_definition`).
    """
    hints = _column_hints(cls)
    columns: list[SnakeColumnInfo] = []
    pk_columns: list[SnakeColumnInfo] = []

    # Walks the MRO (base->child): it also collects the columns inherited from an abstract base.
    for attr, descriptor in collect_inherited(cls, SnakeColumn).items():
        annotation = hints.get(attr)
        type_args = get_args(annotation) if annotation is not None else ()
        inner = type_args[0] if type_args else object
        python_type, inferred_nullable = unwrap_optional(inner)
        # The descriptor keeps the compiled type: class access hands it to the expression, and the
        # SQL layer has no other way to know it (the generic `T` does not survive to runtime).
        descriptor.python_type = python_type
        _guard_enum_declaration(cls, attr, python_type, descriptor)
        _guard_type_params(cls, attr, python_type, descriptor)
        _guard_datetime_declaration(cls, attr, python_type, descriptor)
        info = SnakeColumnInfo(
            name=descriptor.column_name,
            python_type=python_type,
            nullable=inferred_nullable,  # the annotation is the ONLY source: `SnakeColumn[str | None]`
            unique=descriptor.unique,
            default=None if descriptor.default is MISSING else descriptor.default,
            index=descriptor.index,
            db_comment=descriptor.db_comment,
            type_params=descriptor.type_params,
            attr_name=descriptor.attr_name,
            has_default=descriptor.has_default,
            autoincrement=descriptor.autoincrement,
            default_factory=descriptor.default_factory,
            server_default=descriptor.server_default,
            server_default_sql=descriptor.server_default_sql,
            enum_type=descriptor.enum_type,
            enum_storage=descriptor.enum_storage,
        )
        columns.append(info)
        if descriptor.primary_key:
            pk_columns.append(info)

    # The PK is only demanded of what WE GOVERN (kind TABLE). A view may not have one, and neither
    # may a `@snake_db_first` mirror: its legacy schema belongs to the sysadmin and often has none.
    if not pk_columns and kind is SnakeTableKind.TABLE:
        raise SnakeModelDefinitionError(
            f"Model {cls.__name__} has to declare at least one PK (primary_key=True)."
        )

    indexes = _compile_indexes(cls, columns)
    checks = (*_enum_checks(columns), *getattr(cls, "SnakeChecks", ()))

    base_name = table if table is not None else f"{cls.__name__.lower()}s"
    if polymorphic is not None:
        _guard_discriminator(cls, columns, polymorphic)
    return SnakeTableInfo(
        name=f"{prefix}_{base_name}" if prefix else base_name,
        columns=tuple(columns),
        primary_key=SnakePrimaryKeyInfo(columns=tuple(pk_columns)),
        schema=schema,
        database=database,
        db_comment=getattr(cls, "SnakeComment", None),
        indexes=indexes,
        checks=checks,
        kind=kind,
        polymorphic=polymorphic,
    )


def _guard_discriminator(
    cls: type, columns: list[SnakeColumnInfo], polymorphic: SnakePolymorphicInfo
) -> None:
    """The discriminator column has to EXIST and be a `str`, or the hierarchy does not hold up.

    At compile time and not at query time: otherwise the failure shows up as `WHERE
    nonexistent_column = 'dog'` in production. A discriminator's value is a string; an `int` that
    accepts it lies.
    """
    found = next((c for c in columns if c.name == polymorphic.column), None)
    if found is None:  # pragma: no cover - impossible: the column IS the declaration
        return
    if found.python_type is not str:
        raise SnakeModelDefinitionError(
            f"The discriminator '{polymorphic.column}' of {cls.__name__} is "
            f"{found.python_type.__name__}, and it has to be `str`: its value is the name of "
            f"the subclass, and storing it in another type would force a conversion on every query."
        )
