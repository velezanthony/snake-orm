"""Every migration operation has to know how to write itself to a file, and it is checked by RUNNING.

`build_operation` is a chain of `isinstance`, one branch per operation. It fails out loud if
something it does not know reaches it —that is fine— but it fails AT RUNTIME: the day somebody adds
an operation, uses it, generates a migration and only then finds out.

This test brings that forward to the test bench. The list of operations is taken from the MODULE,
not from my memory: of the four times this project has had "a feature implemented in N-1 siblings",
in three of them the list was kept by a person.

AND "FROM THE MODULE" HAS TO MEAN THE WHOLE MODULE, which it did not. The reader asked for
`up_sql`, so `RunPython` —the one operation that has `run` instead, because it carries no SQL— fell
out of the list, out of `_SAMPLES`, and out of every test below. `_Renderer.build_run_python` has
always known how to write it; nothing ever checked that what it writes compiles back. On top of
that the first test carried an `and cls.__name__ != "RunPython"`, which was DEAD —the reader had
already dropped it— and read as a deliberate exemption to anybody auditing the file. Two layers
over one hole, and the outer one was the reason nobody dug. The reader now asks the same question
the sibling tallies ask —`up_sql` OR `run`— and the exemption is gone.

And the check is to RENDER for real, not to look for the `isinstance` in the source. The first
version of this file did exactly that and gave two false positives: `CreateSchema` and `DropSchema`
share a branch with `isinstance(operation, (A, B))`, which the grep could not see. A test that
measures the source code measures the source code; to know whether something works you must call it.

What is NOT done is turning the chain into a dispatch table. It works, it fails loudly and it is on
no hot path: rewriting two hundred-odd correct lines for aesthetics is churn with risk. What was
missing was the NET, and this is it.
"""

from __future__ import annotations

import inspect

import pytest

import snakeorm.migration.operations as operations_module
from snakeorm.expressions import SnakeExpr
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeForeignKeyInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeRelationshipKind,
    SnakeRelationshipInfo,
    SnakeRoutineInfo,
    SnakeTableInfo,
    SnakeTableKind,
    SnakeTriggerEvent,
    SnakeTriggerInfo,
    SnakeTriggerTiming,
)
from snakeorm.migration.render import render_migration
from snakeorm.session import SnakeSession

_ID = SnakeColumnInfo(name="id", python_type=int)
_TABLE = SnakeTableInfo(
    name="cmp_t", columns=(_ID,), primary_key=SnakePrimaryKeyInfo(columns=(_ID,))
)
_VIEW = SnakeTableInfo(
    name="cmp_v",
    columns=(_ID,),
    primary_key=SnakePrimaryKeyInfo(columns=()),
    kind=SnakeTableKind.VIEW,
    view_definition="SELECT 1 AS id",
)
_RELATION = SnakeRelationshipInfo(
    name="other",
    target="Other",
    kind=SnakeRelationshipKind.TO_ONE,
    foreign_key=SnakeForeignKeyInfo(target="Other", pairs=(("id", "id"),)),
)
_CHECK = SnakeCheckInfo(condition=SnakeExpr[int](path=("id",)) > 0, name="ck_cmp")
_ROUTINE = SnakeRoutineInfo(
    name="f", body="CREATE FUNCTION f() RETURNS int AS $$ SELECT 1 $$"
)
_TRIGGER = SnakeTriggerInfo(
    name="tg",
    table="cmp_t",
    timing=SnakeTriggerTiming.AFTER,
    events=(SnakeTriggerEvent.INSERT,),
    body="EXECUTE FUNCTION f()",
)


def forward(session: SnakeSession) -> None:
    """The `forward` of the `RunPython` specimen. It is never CALLED here, only referenced.

    Module level and not a closure on purpose: the renderer writes the callable by its import path,
    so a lambda or a nested function is refused loudly. That is the contract the specimen has to
    honour for the round trip below to mean anything.
    """
    return None


def backward(session: SnakeSession) -> None:
    """The `backward` of the same specimen, so the reversible branch gets rendered too."""
    return None


# A MINIMAL instance of each operation. That this table be complete is exactly what the test
# watches: if a new operation shows up with no entry here, the first test fails and forces one in.
_SAMPLES: dict[str, object] = {
    "CreateTable": (_TABLE,),
    "DropTable": (_TABLE,),
    "AddColumn": (_TABLE, _ID),
    "DropColumn": (_TABLE, _ID),
    "AlterColumn": (_TABLE, _ID, _ID),
    "AlterTableComment": (_TABLE, "the table comment"),
    "RenameColumn": (_TABLE, "old_name", "new_name"),
    "RenameTable": (_TABLE, "cmp_t_renamed"),
    # The two snapshots have to be the SAME table wearing different constraints, or
    # `RebuildTable` refuses to be built. Here they are the same table with none.
    "RebuildTable": (_TABLE, _TABLE),
    "CreateIndex": (_TABLE, SnakeIndexInfo(columns=("id",))),
    "DropIndex": (_TABLE, SnakeIndexInfo(columns=("id",))),
    "AddCheck": (_TABLE, _CHECK),
    "DropCheck": (_TABLE, _CHECK),
    "AddForeignKey": (_TABLE, _RELATION, _TABLE),
    "DropForeignKey": (_TABLE, _RELATION, _TABLE),
    "CreateSchema": ("analytics",),
    "DropSchema": ("analytics",),
    "CreateView": (_VIEW,),
    "DropView": (_VIEW,),
    "AlterView": (_VIEW, _VIEW),
    "CreateFunction": (_ROUTINE,),
    "DropFunction": (_ROUTINE,),
    "AlterFunction": (_ROUTINE, _ROUTINE),
    "CreateTrigger": (_TRIGGER,),
    "DropTrigger": (_TRIGGER,),
    "AlterTrigger": (_TRIGGER, _TRIGGER),
    "RunSQL": ((("UPDATE cmp_t SET id = 1",),)),
    # The one operation with no SQL in it: it is rendered by REFERENCE to two importable functions,
    # which is a branch of the renderer nothing else here exercises.
    "RunPython": (forward, backward),
}


def _concrete_operations() -> list[type]:
    """The operation classes that exist, read from the module and not from a hand-written list.

    An operation is a class that knows how to emit its SQL (`up_sql`) OR to run its logic (`run`) —
    the same question the two coverage tallies in `frameworks/shared/tests/` ask of the same module.
    Asking only for `up_sql` is what left `RunPython` out of this file for as long as it existed:
    a data migration carries no SQL, so it answered no to the only question that was being asked.

    THE PROTOCOLS ARE EXCLUDED BY BEING PROTOCOLS, not by being named. `SnakeOperation` used to be
    struck off by identity, and widening the question above brought its data-side twin
    `SnakeDataOperation` in — a contract, not an operation somebody can put in a migration. Asking
    `_is_protocol` is the same question the sibling tallies ask, and a third contract lands outside
    this list on the day it is written instead of on the day somebody remembers to name it.
    """
    return sorted(
        (
            obj
            for name, obj in vars(operations_module).items()
            if inspect.isclass(obj)
            and not name.startswith("_")
            and not getattr(obj, "_is_protocol", False)
            and (hasattr(obj, "up_sql") or hasattr(obj, "run"))
            and hasattr(obj, "apply_to_state")
        ),
        key=lambda cls: cls.__name__,
    )


def test_the_sample_table_covers_every_operation() -> None:
    """If a new operation shows up, this table says so BEFORE a migration fails.

    It is the half that makes the rest useful: a parametrized test over an incomplete list passes
    just as green, and that trap already showed up in this branch with three tests measuring nothing.

    IT CARRIED AN EXEMPTION AND THE EXEMPTION WAS DEAD. `and cls.__name__ != "RunPython"` excluded
    a name `_concrete_operations()` was not returning anyway, so deleting it changed no result — but
    while it was here it answered the question "why is `RunPython` not in `_SAMPLES`?" with "on
    purpose", and the honest answer was "because the reader could not see it". An exemption that
    covers more than it needs to is an exemption that hides.
    """
    missing = {
        cls.__name__ for cls in _concrete_operations() if cls.__name__ not in _SAMPLES
    }

    assert missing == set(), (
        f"operations with no specimen in the test: {sorted(missing)}"
    )


@pytest.mark.parametrize("name", sorted(_SAMPLES), ids=str)
def test_every_operation_can_be_written_to_a_migration(name: str) -> None:
    """Each operation is written to a file and that file compiles AGAIN.

    It is not enough for `build_operation` not to raise: what matters is that what gets written is
    valid Python that rebuilds the operation. It is point 2 of the 4-point contract, checked for all
    of them at once instead of one by one.
    """
    cls = getattr(operations_module, name)
    arguments = _SAMPLES[name]
    operation = cls(*arguments) if isinstance(arguments, tuple) else cls(arguments)

    source = render_migration("0001_coverage", [operation])

    namespace: dict[str, object] = {}
    exec(compile(source, "0001_coverage.py", "exec"), namespace)  # noqa: S102
    rebuilt = namespace["operations"]

    assert len(rebuilt) == 1  # type: ignore[arg-type]
    assert type(rebuilt[0]).__name__ == name  # type: ignore[index]
