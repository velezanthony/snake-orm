"""Serialization of the migration history to Python SOURCE CODE.

Key decision: `python_type` is a Python `type`; serializing it to JSON would demand a name↔type
registry (a second, worse type system). In `.py` it is an import and a reference: "if the type
comes from Python, the history is written in Python".

`render_migration` returns the text of a file that, on import, rebuilds the operations EXACTLY.
It is readable and editable: tables are pulled out into named variables and reused; every object
is rendered imitating `ruff format` (multiline if it does not fit in 88 columns, double quotes,
default-valued fields omitted), so it passes `ruff check`/`ruff format --check` as is. A
non-literal `default`, or a lambda/closure `default_factory` (no import path), is rejected loudly.
"""

from __future__ import annotations

import keyword
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from decimal import Decimal
from enum import Enum
from typing import get_args, get_origin

from snakeorm.core.placement import DEFAULT_SCHEMA
from snakeorm.core.exceptions import SnakeEmitError, SnakeModelDefinitionError
from snakeorm.expressions import (
    SnakeAnd,
    SnakeArith,
    SnakeComparison,
    SnakeCondition,
    SnakeExpr,
    SnakeInList,
    SnakeIsNotNull,
    SnakeIsNull,
    SnakeLike,
    SnakeNot,
    SnakeOr,
    SnakeValue,
)
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeFkAction,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipInfo,
    SnakeRoutineInfo,
    SnakeServerDefault,
    SnakeTableInfo,
    SnakeTableKind,
    SnakeTriggerInfo,
    SnakeTypeParams,
)
from snakeorm.helpers.pyliteral import str_lit
from snakeorm.migration.ddl import view_fingerprint
from snakeorm.migration.operations import (
    AddCheck,
    AddColumn,
    AddForeignKey,
    AlterColumn,
    AlterTableComment,
    AlterFunction,
    AlterTrigger,
    AlterView,
    CreateFunction,
    CreateIndex,
    CreateSchema,
    CreateTable,
    CreateTrigger,
    CreateView,
    DropCheck,
    DropColumn,
    DropForeignKey,
    DropFunction,
    DropIndex,
    DropSchema,
    DropTable,
    DropTrigger,
    DropView,
    RebuildTable,
    RenameColumn,
    RenameTable,
    RunPython,
    RunSQL,
    SnakeMigrationOperation,
)

_MAX_LINE = 88  # the same default width that `ruff format` uses
_INDENT = 4

# The parameter families come from the UNION, not from this list. `SnakeDateTimeParams` was born
# with the date family and nobody added it here, so every migration with a date column generated a
# file carrying a `NameError`: the name got rendered and never imported. Deriving them makes a new
# family walk in on its own, which is the only thing that keeps this from happening twice.
_PARAM_CLASSES = frozenset(family.__name__ for family in get_args(SnakeTypeParams))

_META_CLASSES = _PARAM_CLASSES | frozenset(
    {
        "SnakeCheckInfo",
        "SnakeColumnInfo",
        "SnakeEnumStorage",
        "SnakeFkAction",
        "SnakeForeignKeyInfo",
        "SnakeIndexInfo",
        "SnakeIndexMethod",
        "SnakeIntSize",
        "SnakeJsonStorage",
        "SnakePrimaryKeyInfo",
        "SnakeRelationshipInfo",
        "SnakeRoutineInfo",
        "SnakeServerDefault",
        "SnakeTriggerEvent",
        "SnakeTriggerInfo",
        "SnakeTriggerTiming",
        "SnakeTableInfo",
        "SnakeTableKind",
        "SnakeRelationshipKind",
    }
)
# Nodes of the boolean AST that `build_condition` knows how to write (the ones that fit in a CHECK
# or in the WHERE of a partial index). They are imported from `snakeorm.expressions`, not `metadata`.
_EXPR_CLASSES = frozenset(
    {
        "SnakeAnd",
        "SnakeArith",
        "SnakeArithOp",
        "SnakeComparison",
        "SnakeExpr",
        "SnakeInList",
        "SnakeIsNotNull",
        "SnakeIsNull",
        "SnakeLike",
        "SnakeNot",
        "SnakeOp",
        "SnakeOr",
    }
)
_OP_CLASSES = frozenset(
    {
        "AddCheck",
        "AddColumn",
        "AddForeignKey",
        "AlterColumn",
        "AlterFunction",
        "AlterTableComment",
        "AlterTrigger",
        "AlterView",
        "CreateFunction",
        "CreateTrigger",
        "CreateIndex",
        "CreateSchema",
        "CreateTable",
        "CreateView",
        "DropCheck",
        "DropColumn",
        "DropForeignKey",
        "DropFunction",
        "DropTrigger",
        "DropIndex",
        "DropSchema",
        "DropTable",
        "DropView",
        "RebuildTable",
        "RenameColumn",
        "RenameTable",
        "RunPython",
        "RunSQL",
    }
)
# Names a table variable may NEVER take (they would collide with the file's own bindings).
_RESERVED = frozenset(
    {"version", "operations", "migration", "Migration"} | _META_CLASSES | _OP_CLASSES
)


# -- rendering IR: a small tree flattened to text imitating `ruff format` -------------------


@dataclass(frozen=True)
class _Scalar:
    """A leaf that is already text (an `int`, a literal, a reference to a variable)."""

    text: str


@dataclass(frozen=True)
class _Tuple:
    """A literal tuple `(a, b, ...)`."""

    items: tuple[_Node, ...]


@dataclass(frozen=True)
class _Call:
    """A call `Name(pos0, pos1, kw=value, ...)`."""

    name: str
    args: tuple[_Node, ...] = ()
    kwargs: tuple[tuple[str, _Node], ...] = field(default_factory=tuple)


_Node = _Scalar | _Tuple | _Call


def _inline(node: _Node) -> str:
    """Renders the node on ONE single line (without deciding whether it fits: just the compact form)."""
    if isinstance(node, _Scalar):
        return node.text
    if isinstance(node, _Tuple):
        inner = ", ".join(_inline(item) for item in node.items)
        if len(node.items) == 1:
            inner += ","  # the comma is mandatory in a one-element tuple
        return f"({inner})"
    parts = [_inline(arg) for arg in node.args]
    parts.extend(f"{name}={_inline(value)}" for name, value in node.kwargs)
    return f"{node.name}({', '.join(parts)})"


def _format(node: _Node, indent: int, col: int, tail: int) -> str:
    """Renders the node fitting into 88 columns: inline if it fits, exploded one per line if not.

    `indent` is the indentation of the line; `col` the column where the node starts; `tail` the
    characters trailing the node (the comma, say). When exploding it adds a trailing comma (magic
    comma) so as to stay stable against `ruff format --check`.
    """
    inline = _inline(node)
    if col + len(inline) + tail <= _MAX_LINE:
        return inline

    child_indent = indent + _INDENT
    pad = " " * child_indent
    if isinstance(node, _Tuple):
        lines = [
            f"{pad}{_format(item, child_indent, child_indent, 1)},"
            for item in node.items
        ]
        return "(\n" + "\n".join(lines) + f"\n{' ' * indent})"
    if isinstance(node, _Call):
        lines = [
            f"{pad}{_format(arg, child_indent, child_indent, 1)}," for arg in node.args
        ]
        for name, value in node.kwargs:
            prefix = f"{name}="
            rendered = _format(value, child_indent, child_indent + len(prefix), 1)
            lines.append(f"{pad}{prefix}{rendered},")
        return f"{node.name}(\n" + "\n".join(lines) + f"\n{' ' * indent})"
    return inline  # a _Scalar that is too long simply cannot be split


_str_lit = str_lit
"""Literal encoder, sitting in `snakeorm.pyliteral` so that the scaffolding shares the very same one
(it heads off a second encoder built out of f-strings, which opened code execution on import)."""


def _identifier(name: str) -> str:
    """Sanitizes a table name into a valid Python identifier to name its variable."""
    cleaned = re.sub(r"\W", "_", name)
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"t_{cleaned}"
    if keyword.iskeyword(cleaned):
        cleaned = f"{cleaned}_"
    return cleaned


class _Renderer:
    """Accumulates the imports it needs while translating the metadata graph into the rendering IR."""

    def __init__(self) -> None:
        self._imports: set[str] = set()  # `import X` statements, stdlib or user code
        self._used: set[str] = set()  # snakeorm class names that turn up

    # -- leaf types and values ------------------------------------------------

    def render_type(self, python_type: object) -> str:
        """Reference to a type along with its import (`int`, `uuid.UUID`, `list[str]`, ...).

        GENERIC ALIASES are rendered recursively together with their arguments: `list[str]` is not a
        `type` but a `GenericAlias`, and reading its `__qualname__` gave a bare `"list"` (the cycle
        quietly stopped closing). The recursion also REGISTERS the import of every argument (`uuid`
        in `list[uuid.UUID]`).
        """
        origin = get_origin(python_type)
        if origin is not None:
            args = ", ".join(self.render_type(arg) for arg in get_args(python_type))
            return f"{self.render_type(origin)}[{args}]"

        if not isinstance(python_type, type):
            raise SnakeModelDefinitionError(
                f"The type {python_type!r} is not renderable in a migration. Types and generic "
                f"aliases (`list[str]`, `dict[str, int]`) are accepted."
            )

        module = python_type.__module__
        qualname = python_type.__qualname__
        if module == "builtins":
            return qualname  # int, str, bool... always in scope, no import
        self._imports.add(f"import {module}")
        return f"{module}.{qualname}"

    def render_default(self, value: object) -> str:
        """Reference to a DDL literal. Literals only; anything else gets rejected.

        An ENUM member is unwrapped down to its value: its `repr` (`<Priority.NORMAL: 1>`) is not
        valid Python, and in the DDL the DEFAULT is the value anyway.
        """
        if isinstance(value, Enum):
            value = value.value
        if value is None or isinstance(value, bool):
            return repr(value)  # None/True/False do not hang on quoting
        if isinstance(value, (int, float)):
            return repr(value)
        if isinstance(value, str):
            return _str_lit(value)
        if isinstance(value, Decimal):
            self._imports.add("import decimal")
            return f"decimal.Decimal({_str_lit(str(value))})"
        raise SnakeModelDefinitionError(
            f"The default {value!r} is not renderable: DDL DEFAULTs must be literals "
            f"(None, bool, int, float, str, Decimal). For a computed value use default_factory."
        )

    def render_factory(self, factory: Callable[..., object]) -> str:
        """Importable reference to a callable by its module + qualname (or class + method).

        It serves `default_factory` and the `forward`/`backward` of a `RunPython`: it is never
        INVOKED, only its import attributes get read, so the signature is moot (`Callable[..., object]`).
        """
        # Pure reflection (`getattr` would hand back `Any`): it is anchored to `object` and narrowed
        # with `isinstance` to return a checked `str`, not an `Any` in disguise. House rule: never `Any`.
        bound_to: object = getattr(factory, "__self__", None)
        name: object = getattr(factory, "__name__", None)
        if isinstance(bound_to, type) and isinstance(name, str) and name:
            # Builtin method bound to a class (datetime.datetime.now, say): its __module__
            # is None, but __self__ hands over the class and __name__ the method.
            return f"{self.render_type(bound_to)}.{name}"
        module: object = getattr(factory, "__module__", None)
        qualname: object = getattr(factory, "__qualname__", None)
        if (
            not isinstance(module, str)
            or not isinstance(qualname, str)
            or "<lambda>" in qualname
            or "<locals>" in qualname
        ):
            raise SnakeModelDefinitionError(
                f"default_factory {factory!r} is not importable: a lambda or a closure has no "
                f"import path and cannot be written into a migration file. Use a module-level "
                f"function (for instance datetime.datetime.now)."
            )
        if module == "builtins":
            return qualname
        self._imports.add(f"import {module}")
        return f"{module}.{qualname}"

    def build_condition(self, node: object) -> _Node:
        """Serializes a node of the boolean AST into Python code, recursively.

        It is what allows a CONDITION (CHECK, partial indexes) to be saved in a readable migration
        file. Whatever cannot be rendered (a subquery, EXISTS) is rejected loudly: it does not fit
        in a Postgres CHECK either, so this is correctness, not a shortcoming.
        """
        if isinstance(node, SnakeExpr):
            self._used.add("SnakeExpr")
            path = _Tuple(tuple(_Scalar(_str_lit(step)) for step in node.path))
            return _Call("SnakeExpr", kwargs=(("path", path),))
        if isinstance(node, SnakeArith):
            self._used.add("SnakeArith")
            self._used.add("SnakeArithOp")
            return _Call(
                "SnakeArith",
                args=(
                    self.build_condition(node.left),
                    _Scalar(f"SnakeArithOp.{node.op.name}"),
                    self.build_condition(node.right),
                ),
            )
        if isinstance(node, SnakeComparison):
            self._used.add("SnakeComparison")
            self._used.add("SnakeOp")
            return _Call(
                "SnakeComparison",
                args=(
                    self.build_condition(node.left),
                    _Scalar(f"SnakeOp.{node.op.name}"),
                    self.build_condition(node.right),
                ),
            )
        if isinstance(node, (SnakeAnd, SnakeOr)):
            name = type(node).__name__
            self._used.add(name)
            parts = _Tuple(tuple(self.build_condition(part) for part in node.parts))
            return _Call(name, kwargs=(("parts", parts),))
        if isinstance(node, SnakeNot):
            self._used.add("SnakeNot")
            return _Call(
                "SnakeNot", kwargs=(("operand", self.build_condition(node.operand)),)
            )
        if isinstance(node, SnakeInList):
            self._used.add("SnakeInList")
            values = _Tuple(tuple(self.build_condition(value) for value in node.values))
            return _Call("SnakeInList", args=(self.build_condition(node.left), values))
        if isinstance(node, (SnakeIsNull, SnakeIsNotNull)):
            name = type(node).__name__
            self._used.add(name)
            return _Call(name, args=(self.build_condition(node.left),))
        if isinstance(node, SnakeLike):
            self._used.add("SnakeLike")
            arguments = [
                self.build_condition(node.left),
                _Scalar(_str_lit(node.pattern)),
            ]
            kwargs: tuple[tuple[str, _Node], ...] = ()
            if node.case_insensitive:
                kwargs = (("case_insensitive", _Scalar("True")),)
            return _Call("SnakeLike", args=tuple(arguments), kwargs=kwargs)
        if isinstance(node, (SnakeCondition, SnakeValue)):
            raise SnakeModelDefinitionError(
                f"{type(node).__name__} cannot be written into a migration file: it carries a "
                f"subquery or a correlation, which cannot be rebuilt from standalone code (and "
                f"which a Postgres CHECK does not accept either). Use a condition over the table's "
                f"own columns."
            )
        # Anything else is a LITERAL (the right-hand side of a comparison, a value inside an IN).
        return _Scalar(self.render_default(node))

    def render_fk_action(self, action: SnakeFkAction) -> str:
        """Reference to an enum member by its name (`SnakeFkAction.CASCADE`)."""
        self._used.add("SnakeFkAction")
        return f"SnakeFkAction.{action.name}"

    def render_server_default(self, value: SnakeServerDefault) -> str:
        """Reference to an enum member by its name (`SnakeServerDefault.NOW`)."""
        self._used.add("SnakeServerDefault")
        return f"SnakeServerDefault.{value.name}"

    def render_type_params(self, params: SnakeTypeParams) -> str:
        """The family's parameters, exactly as they are built (`SnakeDecimalParams(12, 2)`).

        Generic on purpose: it walks the fields of the dataclass, so a NEW family renders itself
        without touching any of this. The only thing to remember is to put its class into
        `_META_CLASSES` so that it shows up in the import block of the generated file.
        """
        name = type(params).__name__
        self._used.add(name)
        args = ", ".join(
            f"{field.name}={self._render_param(getattr(params, field.name))}"
            for field in fields(params)
        )
        return f"{name}({args})"

    def _render_param(self, value: object) -> str:
        """A parameter value: an enum member by its name, or its `repr` if it is a scalar."""
        if isinstance(value, Enum):
            self._used.add(type(value).__name__)
            return f"{type(value).__name__}.{value.name}"
        return repr(value)

    # -- graph structures (they build IR nodes) -------------------------------

    def build_column(self, column: SnakeColumnInfo) -> _Call:
        """Node for a SnakeColumnInfo, leaving out the fields that equal their default."""
        self._used.add("SnakeColumnInfo")
        kwargs: list[tuple[str, _Node]] = [
            ("name", _Scalar(_str_lit(column.name))),
            ("python_type", _Scalar(self.render_type(column.python_type))),
        ]
        if column.nullable:
            kwargs.append(("nullable", _Scalar("True")))
        if column.unique:
            kwargs.append(("unique", _Scalar("True")))
        if column.has_default:
            kwargs.append(("default", _Scalar(self.render_default(column.default))))
            kwargs.append(("has_default", _Scalar("True")))
        if column.index:
            kwargs.append(("index", _Scalar("True")))
        if column.db_comment is not None:
            kwargs.append(("db_comment", _Scalar(_str_lit(column.db_comment))))
        if column.attr_name:
            kwargs.append(("attr_name", _Scalar(_str_lit(column.attr_name))))
        if column.autoincrement:
            kwargs.append(("autoincrement", _Scalar("True")))
        if column.default_factory is not None:
            kwargs.append(
                (
                    "default_factory",
                    _Scalar(self.render_factory(column.default_factory)),
                )
            )
        if column.server_default is not None:
            kwargs.append(
                (
                    "server_default",
                    _Scalar(self.render_server_default(column.server_default)),
                )
            )
        if (params := column.type_params) is not None:
            kwargs.append(("type_params", _Scalar(self.render_type_params(params))))
        if column.enum_type is not None:
            kwargs.append(("enum_type", _Scalar(self.render_type(column.enum_type))))
        if column.enum_storage is not None:
            self._used.add("SnakeEnumStorage")
            kwargs.append(
                (
                    "enum_storage",
                    _Scalar(f"SnakeEnumStorage.{column.enum_storage.name}"),
                )
            )
        if column.server_default_sql is not None:
            kwargs.append(
                ("server_default_sql", _Scalar(_str_lit(column.server_default_sql)))
            )
        return _Call("SnakeColumnInfo", kwargs=tuple(kwargs))

    def build_primary_key(self, pk: SnakePrimaryKeyInfo) -> _Call:
        """Node for a SnakePrimaryKeyInfo (it repeats the columns for readability; see the module)."""
        self._used.add("SnakePrimaryKeyInfo")
        columns = _Tuple(tuple(self.build_column(column) for column in pk.columns))
        return _Call("SnakePrimaryKeyInfo", kwargs=(("columns", columns),))

    def build_check(self, check: SnakeCheckInfo) -> _Call:
        """Node for a SnakeCheckInfo: its serialized condition plus the name if it is explicit."""
        self._used.add("SnakeCheckInfo")
        kwargs: list[tuple[str, _Node]] = [
            ("condition", self.build_condition(check.condition))
        ]
        if check.name is not None:
            kwargs.append(("name", _Scalar(_str_lit(check.name))))
        return _Call("SnakeCheckInfo", kwargs=tuple(kwargs))

    def build_index(self, index: SnakeIndexInfo) -> _Call:
        """Node for a SnakeIndexInfo."""
        self._used.add("SnakeIndexInfo")
        columns = _Tuple(tuple(_Scalar(_str_lit(name)) for name in index.columns))
        kwargs: list[tuple[str, _Node]] = [("columns", columns)]
        if index.unique:
            kwargs.append(("unique", _Scalar("True")))
        if index.name is not None:
            kwargs.append(("name", _Scalar(_str_lit(index.name))))
        if index.where is not None:
            kwargs.append(("where", self.build_condition(index.where)))
        if index.method is not None:
            self._used.add("SnakeIndexMethod")
            kwargs.append(("method", _Scalar(f"SnakeIndexMethod.{index.method.name}")))
        return _Call("SnakeIndexInfo", kwargs=tuple(kwargs))

    def build_foreign_key(self, fk: SnakeForeignKeyInfo) -> _Call:
        """Node for a SnakeForeignKeyInfo (target + pairs + actions)."""
        self._used.add("SnakeForeignKeyInfo")
        pairs = _Tuple(
            tuple(
                _Tuple((_Scalar(_str_lit(local)), _Scalar(_str_lit(remote))))
                for local, remote in fk.pairs
            )
        )
        kwargs: list[tuple[str, _Node]] = [
            ("target", _Scalar(_str_lit(fk.target))),
            ("pairs", pairs),
        ]
        if fk.on_delete is not SnakeFkAction.NO_ACTION:
            kwargs.append(("on_delete", _Scalar(self.render_fk_action(fk.on_delete))))
        if fk.on_update is not SnakeFkAction.NO_ACTION:
            kwargs.append(("on_update", _Scalar(self.render_fk_action(fk.on_update))))
        return _Call("SnakeForeignKeyInfo", kwargs=tuple(kwargs))

    def build_relationship(self, rel: SnakeRelationshipInfo) -> _Call:
        """Node for a SnakeRelationshipInfo."""
        self._used.add("SnakeRelationshipInfo")
        # Symbolic (`SnakeRelationshipKind.TO_ONE`), not the string: rename the member and the file
        # stops compiling instead of loading a string with no meaning. Histories carrying the old
        # string keep loading (`coerce` converts them).
        self._used.add("SnakeRelationshipKind")
        kwargs: list[tuple[str, _Node]] = [
            ("name", _Scalar(_str_lit(rel.name))),
            ("target", _Scalar(_str_lit(rel.target))),
            ("kind", _Scalar(f"SnakeRelationshipKind.{rel.kind.name}")),
            ("foreign_key", self.build_foreign_key(rel.foreign_key)),
        ]
        if rel.target_table:
            # The target ALREADY RESOLVED (`schema.table`): it makes the migration SELF-CONTAINED —no
            # need to import the target model on apply to resolve the FK by name— and it allows the FK to
            # be INLINED inside the `CREATE TABLE` on SQLite (which takes no later `ADD CONSTRAINT`).
            kwargs.append(("target_table", _Scalar(_str_lit(rel.target_table))))
        return _Call("SnakeRelationshipInfo", kwargs=tuple(kwargs))

    def build_routine(self, routine: SnakeRoutineInfo) -> _Call:
        """Node for a SnakeRoutineInfo (name + raw body; it is rendered inline in the operation)."""
        self._used.add("SnakeRoutineInfo")
        kwargs: list[tuple[str, _Node]] = [
            ("name", _Scalar(_str_lit(routine.name))),
            ("body", _Scalar(_str_lit(routine.body))),
        ]
        if routine.schema != DEFAULT_SCHEMA:
            kwargs.append(("schema", _Scalar(_str_lit(routine.schema))))
        return _Call("SnakeRoutineInfo", kwargs=tuple(kwargs))

    def build_trigger(self, trigger: SnakeTriggerInfo) -> _Call:
        """Node for a SnakeTriggerInfo. Enums are rendered by their member (`SnakeTriggerTiming.AFTER`,
        not `"AFTER"`): rename the member and the file stops compiling. Same as with `SnakeFkAction`."""
        self._used.update(
            {"SnakeTriggerInfo", "SnakeTriggerTiming", "SnakeTriggerEvent"}
        )
        events = _Tuple(
            tuple(
                _Scalar(f"SnakeTriggerEvent.{event.name}") for event in trigger.events
            )
        )
        kwargs: list[tuple[str, _Node]] = [
            ("name", _Scalar(_str_lit(trigger.name))),
            ("table", _Scalar(_str_lit(trigger.table))),
            ("timing", _Scalar(f"SnakeTriggerTiming.{trigger.timing.name}")),
            ("events", events),
            ("body", _Scalar(_str_lit(trigger.body))),
        ]
        if trigger.schema != DEFAULT_SCHEMA:
            kwargs.append(("schema", _Scalar(_str_lit(trigger.schema))))
        if not trigger.for_each_row:
            kwargs.append(("for_each_row", _Scalar("False")))
        return _Call("SnakeTriggerInfo", kwargs=tuple(kwargs))

    def build_table(self, table: SnakeTableInfo) -> _Call:
        """Node for a complete SnakeTableInfo (what gets assigned to a named variable)."""
        self._used.add("SnakeTableInfo")
        columns = _Tuple(tuple(self.build_column(column) for column in table.columns))
        kwargs: list[tuple[str, _Node]] = [
            ("name", _Scalar(_str_lit(table.name))),
            ("columns", columns),
            ("primary_key", self.build_primary_key(table.primary_key)),
        ]
        if table.relationships:
            rels = _Tuple(
                tuple(self.build_relationship(rel) for rel in table.relationships)
            )
            kwargs.append(("relationships", rels))
        if table.checks:
            checks = _Tuple(tuple(self.build_check(check) for check in table.checks))
            kwargs.append(("checks", checks))
        if table.database != "default":
            kwargs.append(("database", _Scalar(_str_lit(table.database))))
        if table.schema != DEFAULT_SCHEMA:
            kwargs.append(("schema", _Scalar(_str_lit(table.schema))))
        if table.db_comment is not None:
            kwargs.append(("db_comment", _Scalar(_str_lit(table.db_comment))))
        if table.indexes:
            indexes = _Tuple(tuple(self.build_index(index) for index in table.indexes))
            kwargs.append(("indexes", indexes))
        if table.kind is not SnakeTableKind.TABLE:
            self._used.add("SnakeTableKind")
            kwargs.append(("kind", _Scalar(f"SnakeTableKind.{table.kind.name}")))
        if table.kind is SnakeTableKind.VIEW:
            # What goes into the migration file is always the FINGERPRINT, that is SQL already
            # compiled with the canonical dialect, even if the view was declared with `query=`. The
            # snapshot has to be reproducible: the same migration from any machine and without
            # depending on the local engine. A `SnakeQuery` serialized into the file would tie the
            # migration to the version of the model, which is just what a snapshot exists NOT to do.
            kwargs.append(
                ("view_definition", _Scalar(_str_lit(view_fingerprint(table))))
            )
        if table.depends_on:
            depends = _Tuple(
                tuple(_Scalar(_str_lit(name)) for name in table.depends_on)
            )
            kwargs.append(("depends_on", depends))
        return _Call("SnakeTableInfo", kwargs=tuple(kwargs))

    def build_operation(
        self,
        operation: SnakeMigrationOperation,
        var_of: Callable[[SnakeTableInfo], str],
    ) -> _Call:
        """Node for an operation, referencing the tables by their named variable."""
        if isinstance(operation, CreateTable):
            self._used.add("CreateTable")
            return _Call("CreateTable", args=(_Scalar(var_of(operation.table)),))
        if isinstance(operation, DropTable):
            self._used.add("DropTable")
            return _Call("DropTable", args=(_Scalar(var_of(operation.table)),))
        if isinstance(operation, AddColumn):
            self._used.add("AddColumn")
            return _Call(
                "AddColumn",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_column(operation.column),
                ),
            )
        if isinstance(operation, DropColumn):
            self._used.add("DropColumn")
            return _Call(
                "DropColumn",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_column(operation.column),
                ),
            )
        if isinstance(operation, AlterColumn):
            self._used.add("AlterColumn")
            return _Call(
                "AlterColumn",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_column(operation.old),
                    self.build_column(operation.new),
                ),
            )
        if isinstance(operation, AlterTableComment):
            self._used.add("AlterTableComment")
            previous = (
                _Scalar(_str_lit(operation.previous))
                if operation.previous is not None
                else _Scalar("None")
            )
            return _Call(
                "AlterTableComment",
                args=(_Scalar(var_of(operation.table)),),
                kwargs=(("previous", previous),),
            )
        if isinstance(operation, (CreateSchema, DropSchema)):
            name = type(operation).__name__
            self._used.add(name)
            return _Call(name, args=(_Scalar(_str_lit(operation.schema)),))
        if isinstance(operation, RenameColumn):
            self._used.add("RenameColumn")
            return _Call(
                "RenameColumn",
                args=(_Scalar(var_of(operation.table)),),
                kwargs=(
                    ("old_name", _Scalar(_str_lit(operation.old_name))),
                    ("new_name", _Scalar(_str_lit(operation.new_name))),
                ),
            )
        if isinstance(operation, RebuildTable):
            self._used.add("RebuildTable")
            kwargs: tuple[tuple[str, _Node], ...] = ()
            if operation.triggers:
                # The triggers are written INSIDE the operation and not as a table variable: they
                # belong to this rebuild, which is the only thing that recreates them, and a
                # `SnakeTableInfo` has nowhere to put one. Omitted when empty so a rebuild over a
                # table with no triggers writes the same line it always did.
                kwargs = (
                    (
                        "triggers",
                        _Tuple(
                            tuple(
                                self.build_trigger(trigger)
                                for trigger in operation.triggers
                            )
                        ),
                    ),
                )
            return _Call(
                "RebuildTable",
                args=(
                    _Scalar(var_of(operation.before)),
                    _Scalar(var_of(operation.after)),
                ),
                kwargs=kwargs,
            )
        if isinstance(operation, RenameTable):
            self._used.add("RenameTable")
            return _Call(
                "RenameTable",
                args=(_Scalar(var_of(operation.table)),),
                kwargs=(("new_name", _Scalar(_str_lit(operation.new_name))),),
            )
        if isinstance(operation, AddCheck):
            self._used.add("AddCheck")
            return _Call(
                "AddCheck",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_check(operation.check),
                ),
            )
        if isinstance(operation, DropCheck):
            self._used.add("DropCheck")
            return _Call(
                "DropCheck",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_check(operation.check),
                ),
            )
        if isinstance(operation, CreateIndex):
            self._used.add("CreateIndex")
            return _Call(
                "CreateIndex",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_index(operation.index),
                ),
            )
        if isinstance(operation, DropIndex):
            self._used.add("DropIndex")
            return _Call(
                "DropIndex",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_index(operation.index),
                ),
            )
        if isinstance(operation, AddForeignKey):
            self._used.add("AddForeignKey")
            return _Call(
                "AddForeignKey",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_relationship(operation.relationship),
                    _Scalar(var_of(operation.target)),
                ),
            )
        if isinstance(operation, DropForeignKey):
            self._used.add("DropForeignKey")
            return _Call(
                "DropForeignKey",
                args=(
                    _Scalar(var_of(operation.table)),
                    self.build_relationship(operation.relationship),
                    _Scalar(var_of(operation.target)),
                ),
            )
        if isinstance(operation, CreateView):
            self._used.add("CreateView")
            return _Call("CreateView", args=(_Scalar(var_of(operation.view)),))
        if isinstance(operation, DropView):
            self._used.add("DropView")
            return _Call("DropView", args=(_Scalar(var_of(operation.view)),))
        if isinstance(operation, AlterView):
            self._used.add("AlterView")
            return _Call(
                "AlterView",
                args=(_Scalar(var_of(operation.old)), _Scalar(var_of(operation.new))),
            )
        if isinstance(operation, CreateTrigger):
            self._used.add("CreateTrigger")
            return _Call(
                "CreateTrigger", args=(self.build_trigger(operation.definition),)
            )
        if isinstance(operation, DropTrigger):
            self._used.add("DropTrigger")
            return _Call(
                "DropTrigger", args=(self.build_trigger(operation.definition),)
            )
        if isinstance(operation, AlterTrigger):
            self._used.add("AlterTrigger")
            return _Call(
                "AlterTrigger",
                args=(
                    self.build_trigger(operation.old),
                    self.build_trigger(operation.new),
                ),
            )
        if isinstance(operation, CreateFunction):
            self._used.add("CreateFunction")
            return _Call(
                "CreateFunction", args=(self.build_routine(operation.definition),)
            )
        if isinstance(operation, DropFunction):
            self._used.add("DropFunction")
            return _Call(
                "DropFunction", args=(self.build_routine(operation.definition),)
            )
        if isinstance(operation, AlterFunction):
            self._used.add("AlterFunction")
            return _Call(
                "AlterFunction",
                args=(
                    self.build_routine(operation.old),
                    self.build_routine(operation.new),
                ),
            )
        if isinstance(operation, RunSQL):
            return self.build_run_sql(operation)
        if isinstance(operation, RunPython):
            return self.build_run_python(operation)
        raise SnakeModelDefinitionError(
            f"render does not know how to serialise the operation {type(operation).__name__!r}."
        )

    def build_run_sql(self, operation: RunSQL) -> _Call:
        """Node for a `RunSQL`: emits `up` (and `down` if there is one) as a str or tuple of raw str."""
        self._used.add("RunSQL")
        kwargs: list[tuple[str, _Node]] = [("up", self._render_sql_arg(operation.up))]
        if operation.down is not None:
            kwargs.append(("down", self._render_sql_arg(operation.down)))
        return _Call("RunSQL", kwargs=tuple(kwargs))

    def build_run_python(self, operation: RunPython) -> _Call:
        """Node for a `RunPython`: references `forward` (and `backward`) by its import path.

        Same as `default_factory`: the functions have to be importable (at module level). They are
        rendered as `module.qualname` (with their import); a lambda or closure is rejected loudly.
        """
        self._used.add("RunPython")
        args: list[_Node] = [_Scalar(self.render_factory(operation.forward))]
        if operation.backward is not None:
            args.append(_Scalar(self.render_factory(operation.backward)))
        return _Call("RunPython", args=tuple(args))

    def _render_sql_arg(self, sql: str | tuple[str, ...]) -> _Node:
        """Renders the `up`/`down` of a `RunSQL`: a str as a literal; a tuple as a tuple of literals."""
        if isinstance(sql, str):
            return _Scalar(_str_lit(sql))
        return _Tuple(tuple(_Scalar(_str_lit(statement)) for statement in sql))

    def import_roots(self) -> set[str]:
        """Top-level names the imports bind (so that no variable ever tramples on them)."""
        return {
            statement.removeprefix("import ").split(".", 1)[0]
            for statement in self._imports
        }

    def imports_block(self) -> list[str]:
        """Builds the import lines of the file (stdlib/user + metadata + migration)."""
        lines: list[str] = sorted(self._imports)
        if lines:
            lines.append("")
        meta = sorted(name for name in self._used if name in _META_CLASSES)
        if meta:
            lines.append("from snakeorm.metadata import (")
            lines.extend(f"    {name}," for name in meta)
            lines.append(")")
        expressions = sorted(name for name in self._used if name in _EXPR_CLASSES)
        if expressions:
            lines.append("from snakeorm.expressions import (")
            lines.extend(f"    {name}," for name in expressions)
            lines.append(")")
        orphans = sorted(self._used - _META_CLASSES - _EXPR_CLASSES - _OP_CLASSES)
        if orphans:
            # Without this the name drops out of the block IN SILENCE and the file blows up on
            # import, that is on applying the migration: the worst moment to find out. Failing here
            # means failing while generating it, with the name right in front of you.
            raise SnakeEmitError(
                f"The renderer uses names it does not know how to import: {', '.join(orphans)}. "
                f"Register them in _META_CLASSES, _EXPR_CLASSES or _OP_CLASSES of "
                f"migration/render.py, or the generated file will fail with a NameError on apply."
            )
        ops = sorted(name for name in self._used if name in _OP_CLASSES)
        lines.append("from snakeorm.migration import (")
        lines.extend(f"    {name}," for name in ops)
        lines.append("    Migration,")
        lines.append(")")
        return lines


def render_condition(condition: SnakeCondition) -> tuple[str, list[str]]:
    """Renders a condition into `(code, import lines)`.

    It hands the imports back separately because whoever embeds it (a CHECK constraint inside its
    `SnakeCheckInfo`, the WHERE of a partial index) has to merge them with its own in the header of
    the file. Raises `SnakeModelDefinitionError` if the AST carries anything not rebuildable.
    """
    renderer = _Renderer()
    node = renderer.build_condition(condition)
    return _inline(node), renderer.imports_block()


def _referenced_tables(operation: SnakeMigrationOperation) -> list[SnakeTableInfo]:
    """The tables an operation references, in order (source and, where it applies, target)."""
    if isinstance(operation, (AddForeignKey, DropForeignKey)):
        return [operation.table, operation.target]
    if isinstance(
        operation,
        (
            CreateTable,
            DropTable,
            AddColumn,
            DropColumn,
            AlterColumn,
            AlterTableComment,
            CreateIndex,
            DropIndex,
            AddCheck,
            DropCheck,
            RenameColumn,
            RenameTable,
        ),
    ):
        return [operation.table]
    if isinstance(operation, (CreateView, DropView)):
        return [operation.view]
    if isinstance(operation, AlterView):
        return [operation.old, operation.new]
    if isinstance(operation, RebuildTable):
        return [operation.before, operation.after]
    return []


def _collect_tables(
    operations: Sequence[SnakeMigrationOperation],
) -> list[SnakeTableInfo]:
    """Distinct tables (by structural equality) in order of first appearance."""
    distinct: list[SnakeTableInfo] = []
    for operation in operations:
        for table in _referenced_tables(operation):
            if table not in distinct:
                distinct.append(table)
    return distinct


def _assign_names(tables: list[SnakeTableInfo], reserved: set[str]) -> dict[int, str]:
    """Assigns each table (by id) a sanitized, unique variable; disambiguates with a number suffix."""
    used = set(reserved)
    names: dict[int, str] = {}
    for table in tables:
        base = _identifier(table.name)
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        names[id(table)] = candidate
    return names


def render_migration(
    version: str,
    operations: Sequence[SnakeMigrationOperation],
    replaces: Sequence[str] = (),
) -> str:
    """Generates the text of a migration file that rebuilds `operations` when it is imported.

    It exposes `version`, `operations` and `migration: Migration`. `replaces` are the versions that
    this file SUPERSEDES (a squash); it is written only when there is one (a normal migration does not
    shift a single byte) and it must be written: the runner needs it so as not to rerun a squash over
    a DB that is already migrated.
    """
    renderer = _Renderer()

    tables = _collect_tables(operations)
    table_nodes = [(table, renderer.build_table(table)) for table in tables]

    reserved = set(_RESERVED) | renderer.import_roots()
    names = _assign_names(tables, reserved)

    def var_of(table: SnakeTableInfo) -> str:
        """The variable for a table; it matches by identity and, failing that, by structural equality."""
        name = names.get(id(table))
        if name is not None:
            return name
        for (
            original
        ) in tables:  # a different object but structurally equal (earlier dedup)
            if original == table:
                return names[id(original)]
        raise SnakeModelDefinitionError(  # pragma: no cover - defensive
            f"An operation's table {table.name!r} was not collected as a variable."
        )

    operation_nodes = [
        renderer.build_operation(operation, var_of) for operation in operations
    ]

    lines = [
        '"""Migration generated by SnakeORM. Editable by hand."""',
        "",
        "from __future__ import annotations",
        "",
    ]
    lines.extend(renderer.imports_block())
    lines.extend(["", f"version = {_str_lit(version)}", ""])

    for table, node in table_nodes:
        name = names[id(table)]
        rendered = _format(node, 0, len(name) + len(" = "), 0)
        lines.append(f"{name} = {rendered}")
        lines.append("")

    lines.append("operations = [")
    lines.extend(
        f"    {_format(node, _INDENT, _INDENT, 1)}," for node in operation_nodes
    )
    lines.append("]")
    if replaces:
        lines.extend(["", "replaces = ["])
        lines.extend(f"    {_str_lit(version)}," for version in replaces)
        lines.append("]")
        lines.extend(
            [
                "",
                "migration = Migration(",
                "    version=version, operations=tuple(operations), replaces=tuple(replaces)",
                ")",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "migration = Migration(version=version, operations=tuple(operations))",
                "",
            ]
        )
    return "\n".join(lines)
