"""`docs/users/reference/limits.md` says what the ORM does NOT do. This RUNS it.

That page is the one somebody reads to decide whether this ORM is any use to them, so an entry that
stopped being true is not a stale note — it is a decision taken on bad information. And they DO stop
being true, which is the whole reason this file exists: five entries fell off the page between phase
seven and phase eight, one of them the autoincrement toggle, which claimed the migration did not
emit an `AlterColumn` while it emitted one that the server rejected outright.

HOW IT IS ANCHORED, AND THE TRAP IT REFUSES. The obvious build is a parser that reads the prose and
works out what to check. That is a natural-language detector, and this repository has already paid
for one: `test_strings_are_english` promised its own name and delivered "nothing matched my word
list", so everything outside the list passed unseen. A blacklist FAILS OPEN. So the checking is not
derived from the page at all — every claim has its check WRITTEN BY HAND below, and what the page is
used for is one thing only: an EXISTENCE, which is mechanical.

The anchor is the bold text that opens each bullet. Not the line number, which expires on the first
edit; not a paraphrase, which drifts. The bold lead is what an author must retype to change what the
page promises, so a rewritten claim shows up here as an anchor nobody knows.

BOTH DIRECTIONS ARE GUARDED, and neither is decoration:

- an anchor on the page that no table below mentions fails, so a new limit cannot be published
  without somebody deciding how it gets exercised;
- an entry in a table that is no longer on the page fails, so a claim that gets deleted or reworded
  cannot leave a check behind quietly asserting a promise nobody makes any more.

AND BECAUSE THE ANCHOR IS THE IDENTITY OF A CLAIM, THE PAGE MAY NOT PUBLISH TWO BULLETS THAT OPEN
WITH THE SAME BOLD TEXT — in either language. That was an implicit requirement for as long as this
file has existed and nothing held it: the parse wrote into a dictionary, so a repeated anchor
collapsed into one entry inside the parser and both directions above ran over the survivor, green,
while the page published a claim nothing exercised. The reading is a LIST now and the dictionary is
derived from it, so the two counts can be compared — and they are compared against a third, the
bullets the page opens, which catches the opposite failure of an anchoring regex that stopped
matching. One equality, no magic number to keep up to date as the page grows.

WHAT IS NOT EXERCISED IS DECLARED, WITH ITS REASON, in `_NOT_EXECUTABLE` — the same shape as
`_OUT_OF_SCOPE` in `frameworks/shared/tests/test_orm_api_coverage.py` (which sits beside a `_NOT_YET`
holding what is merely owed, a split this file has no use for), and for the same reason:
a gap written down is a gap somebody can close, while a gap left out is one nobody can see. A claim
about what a type CHECKER accepts cannot be run by a test that runs no checker, and saying so is
worth more than a check that pretends.

NOTHING HERE TOUCHES PROCESS-GLOBAL STATE AT IMPORT TIME, and that rule was bought with a failure.
A signal handler used to be connected at module level; `_HANDLERS` is a global dictionary that
`src/test/session/` empties with `disconnect_all()`, so in the FULL suite the handler was gone
before this file ran and the check that needed it failed — green on its own, red in the run, far
from the file that cleared it. A check that needs global state now sets it up and tears it down
inside itself. Audited alongside it: no converter is registered here (`_TO_DB`/`_FROM_DB` are
cleared by three other files), and the one warning asserted on —`warn_bulk_skips_signals`— is the
one that does NOT dedupe per process, unlike `_warn_reduced_fidelity`, which fires once and would
have been the same bug in a second flavour. What is left at import is the model registry, which
nothing in the suite resets.

AND THE CHECKS FOLLOW THE CODE, NOT THE PAGE. Where the two disagree, the check asserts what the ORM
actually does and the divergence is reported for the page to be fixed by hand — a test rewritten to
agree with a wrong sentence is a test that certifies the wrong sentence.
"""

from __future__ import annotations

import argparse
import dataclasses
import decimal
import inspect
import pathlib
import re
import tempfile
import uuid
import warnings
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta, timezone

import pytest

from snakeorm import (
    AsyncSession,
    MySQLDialect,
    PostgresDialect,
    SnakeColumn,
    SnakeCondition,
    SnakeDateTimeParams,
    SnakeDecimalParams,
    SnakeDialectError,
    SnakeEmitError,
    SnakeIntParams,
    SnakeIntSize,
    SnakeJsonParams,
    SnakeJsonStorage,
    SnakeMigrationError,
    SnakeModel,
    SnakeModelDefinitionError,
    SnakeQuery,
    SnakeRelationshipNotLoaded,
    SnakeResult,
    SnakeSession,
    SnakeSignal,
    SnakeStrParams,
    SnakeToMany,
    SnakeToOne,
    SnakeUnsupportedFeature,
    SnakeUtc,
    SnakeValueError,
    SnakeWarning,
    SQLiteDialect,
    SQLiteDriver,
    TimeoutDriver,
    snake_auto,
    snake_check,
    snake_column,
    snake_datetime,
    snake_datetimetz,
    snake_decimal,
    snake_discriminator,
    snake_float,
    snake_int,
    snake_json,
    snake_link,
    snake_model,
    snake_result,
    snake_str,
    snake_table,
    snake_to_many,
    snake_to_one,
    sum_,
)
from snakeorm.fields import MISSING
from snakeorm.core.signals import connect, disconnect_all
from snakeorm.registry import SnakeRegistry
from snakeorm.session.guards import _guard_declared_limits, _guard_required_values
from snakeorm.dialects.capabilities import Cap, Degraded, Nope
from snakeorm.introspection.postgres import _PYTHON_TYPES as _POSTGRES_PYTHON_TYPES
from snakeorm.introspection.sqlite import _python_type as _sqlite_python_type
from snakeorm.introspection.unsupported import (
    expression_index_warning,
    routine_warning,
    trigger_warning,
    unrepresentable_column_warning,
)
from snakeorm.migration import (
    diff_schema,
    emit_alter_column,
    emit_column_comment,
    emit_comments,
    emit_create_index,
    emit_create_table,
    realize,
    squash,
)
from snakeorm.core.config import DEFAULT_DATABASE
from snakeorm.cli.app import _cmd_squash
from snakeorm.migration.loader import Migration
from snakeorm.migration.operations import (
    AddCheck,
    AddColumn,
    AlterColumn,
    AlterTableComment,
    CreateIndex,
    CreateSchema,
    CreateTable,
    DropColumn,
    DropForeignKey,
    RebuildTable,
    RunPython,
    RunSQL,
    SnakeMigrationOperation,
)
from snakeorm.migration.asyncrunner import _reject_data_operation
from snakeorm.migration.render import render_migration
from snakeorm.migration.renames import format_rename_hint, rename_suggestions
from snakeorm.metadata.polymorphic import SnakePolymorphicInfo
from snakeorm.metadata import (
    SnakeCheckInfo,
    SnakeColumnInfo,
    SnakeIndexInfo,
    SnakePrimaryKeyInfo,
    SnakeTableInfo,
)
from snakeorm.metadata.relationship_kind import SnakeRelationshipKind
from snakeorm.expressions import SnakeExpr, SnakeTupleIn, SnakeValue
from snakeorm.sql import emit_condition
from snakeorm.session.planning import plan_annotate, routine_name
from snakeorm.fields import SNAKE_FIELD_SPECIFIERS

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PAGE = _ROOT / "docs" / "users" / "reference" / "limits.md"
_SPANISH_PAGE = _PAGE.with_suffix("").with_suffix(".es.md")

_POSTGRES = PostgresDialect()
_MYSQL = MySQLDialect()
_SQLITE = SQLiteDialect()


# --------------------------------------------------------------------------------------------
# The page, read as a list of anchors and nothing else.
# --------------------------------------------------------------------------------------------

_BULLET = re.compile(r"^\s*- \*\*")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def page_bullets(page: pathlib.Path = _PAGE) -> int:
    """How many lines of the page OPEN a bullet, counted without the parser's own regexes.

    A plain `startswith` on purpose. This is the independent measure the equality below compares the
    parse against, and a count taken with `_BULLET`/`_BOLD` would move with them and therefore see
    nothing when one of them stops matching.
    """
    return sum(
        1
        for line in page.read_text(encoding="utf-8").split("\n")
        if line.lstrip().startswith("- **")
    )


def page_claim_pairs(page: pathlib.Path = _PAGE) -> list[tuple[str, str]]:
    """Every claim of the page IN PUBLICATION ORDER, as `(bold lead, the `## ` section)`.

    THE READING IS A LIST AND THE DICTIONARY IS DERIVED FROM IT, which is the whole point of the
    split. While the parse wrote straight into a dictionary, two bullets opening with the same bold
    lead collapsed into ONE entry inside this function — before any guard downstream could look. The
    evidence was destroyed by the thing meant to gather it, and both directions below then ran over
    the survivor, which quietly answered for the claim that had disappeared.

    The bold lead can wrap onto the next line, so the lines are joined until the closing `**` shows
    up. Only the FIRST bold run of a bullet is the anchor: several bullets emphasise a second phrase
    further in, and taking the last one would move the anchor every time the prose is edited.
    """
    lines = page.read_text(encoding="utf-8").split("\n")
    pairs: list[tuple[str, str]] = []
    section = ""
    for index, line in enumerate(lines):
        if line.startswith("## "):
            section = line[3:].strip()
        if not _BULLET.match(line):
            continue
        buffer = line.lstrip()[2:]
        cursor = index
        while buffer.count("**") < 2 and cursor + 1 < len(lines):
            cursor += 1
            buffer += " " + lines[cursor].strip()
        found = _BOLD.match(buffer.strip())
        if found is not None:
            pairs.append((found.group(1), section))
    return pairs


def page_claims(page: pathlib.Path = _PAGE) -> dict[str, str]:
    """Every claim of the page, as `bold lead -> the `## ` section it lives under`.

    Derived from `page_claim_pairs()` and never parsed on its own. The anchor IS the identity of a
    claim here, so two bullets sharing one are indistinguishable in this mapping BY CONSTRUCTION;
    what keeps that from hiding a claim is the rule that the page may not publish two, held by
    `test_every_bullet_of_the_page_is_a_claim_of_its_own` over the list this derives from.
    """
    return dict(page_claim_pairs(page))


def _claims_per_section(page: pathlib.Path) -> list[tuple[str, int]]:
    """How many claims each `## ` section of a page carries, in the order they are published."""
    counts: dict[str, int] = {}
    for _, section in page_claim_pairs(page):
        counts[section] = counts.get(section, 0) + 1
    return list(counts.items())


# --------------------------------------------------------------------------------------------
# A domain of its own. Small, and named so nothing collides with another suite's registry.
# --------------------------------------------------------------------------------------------


@snake_model(table="limits_makers")
class LimitsMaker(SnakeModel):
    """The far end of a to-one, so an unloaded relation has something to refuse to load."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    widgets: SnakeToMany[LimitsWidget] = snake_to_many("maker")


@snake_model(table="limits_widgets")
class LimitsWidget(SnakeModel):
    """One column per family the page makes a promise about."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    ratio: SnakeColumn[float | None] = snake_float()
    payload: SnakeColumn[dict] = snake_json()
    price: SnakeColumn[decimal.Decimal | None] = snake_decimal(precision=12, scale=2)
    instant: SnakeColumn[SnakeUtc | None] = snake_datetimetz()
    wall: SnakeColumn[datetime | None] = snake_datetime()
    maker_id: SnakeColumn[int] = snake_int()
    maker: SnakeToOne[LimitsMaker] = snake_to_one(maker_id)


@snake_model(table="limits_beasts")
class LimitsBeast(SnakeModel):
    """The base of a polymorphic hierarchy: it owns the table and sees every row in it."""

    id: SnakeColumn[int] = snake_auto()
    kind: SnakeColumn[str] = snake_discriminator()
    name: SnakeColumn[str] = snake_str()


@snake_model(discriminator_value="dog")
class LimitsDog(LimitsBeast):
    """A child, with its own column declared the way the page says it has to be: nullable."""

    breed: SnakeColumn[str | None] = snake_str()


@snake_model(table="limits_audited")
class LimitsAudited(SnakeModel):
    """A model with a signal connected, so a bulk write has something it could have fired."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()


@snake_result
class LimitsTotals(SnakeResult[LimitsMaker]):
    """A result declared over `LimitsMaker`, to hand `annotate` a query of the WRONG model."""

    maker: LimitsMaker
    total: int


snake_link()


@pytest.fixture()
def sqlite_session() -> Iterator[SnakeSession]:
    """An in-memory SQLite session with the two tables created.

    SQLite is not a stand-in for a server here: several of these claims are ABOUT SQLite, and the
    rest are about the ORM's own Python-side guards, which run before any driver is spoken to.
    """
    driver = SQLiteDriver.connect(":memory:")
    for model in (LimitsMaker, LimitsWidget, LimitsBeast, LimitsAudited):
        driver.execute(emit_create_table(snake_table(model), _SQLITE), ())
    driver.commit()
    try:
        yield SnakeSession(driver, _SQLITE)
    finally:
        driver.close()


def _probe_column(*, autoincrement: bool = False) -> SnakeColumnInfo:
    """A plain `int` column, optionally autoincrementing, for the migration operations."""
    return SnakeColumnInfo(
        name="code", python_type=int, autoincrement=autoincrement, db_comment="a note"
    )


def _probe_table(column: SnakeColumnInfo) -> SnakeTableInfo:
    """A one-column table in a named schema, carrying a comment on both the table and the column."""
    return SnakeTableInfo(
        name="limits_probe",
        schema="app",
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=(column,)),
        db_comment="a table note",
    )


def _nothing(session: SnakeSession) -> None:
    """A `RunPython` forward that does nothing: what is under test is the MISSING backward."""


# --------------------------------------------------------------------------------------------
# The checks. One function per claim, spelled out, no inference from the prose.
# --------------------------------------------------------------------------------------------


def _check_equality_is_a_condition() -> None:
    """`==` on a class expression builds SQL, and the truthiness trap the page warns about."""
    condition = LimitsWidget.id == 100

    assert isinstance(condition, SnakeCondition)
    assert bool(condition) is True, (
        "the page warns that `assert Model.x == v` always passes"
    )


def _check_field_specifiers_are_duplicated_five_times() -> None:
    """PEP 681 forces the tuple to be REPEATED at each `dataclass_transform`; the page says five."""
    written = {
        path.relative_to(_ROOT): path.read_text(encoding="utf-8").count(
            "field_specifiers="
        )
        for path in sorted((_ROOT / "src" / "snakeorm").rglob("*.py"))
    }
    copies = sum(written.values())

    assert copies == 5, (
        f"the page says the tuple is written out five times; there are {copies}: "
        f"{ {str(path): count for path, count in written.items() if count} }"
    )
    assert SNAKE_FIELD_SPECIFIERS, (
        "the canonical reference has to exist for the five copies to be kept in sync against it"
    )


def _check_streaming_refuses_a_to_many_include() -> None:
    """`iterate()` exists on both sessions, refuses a to-many include or a prefetch, takes a to-one."""
    assert callable(SnakeSession.iterate) and callable(AsyncSession.iterate)

    with pytest.raises(SnakeUnsupportedFeature, match="to-many include"):
        SnakeSession._guard_streamable(
            SnakeQuery(LimitsMaker).include(LimitsMaker.widgets)
        )

    SnakeSession._guard_streamable(SnakeQuery(LimitsWidget).include(LimitsWidget.maker))


def _check_only_does_not_combine_with_include() -> None:
    """`only()` beside an `include()` is REFUSED, and the refusal names the knob it cannot honour."""
    query = SnakeQuery(LimitsWidget).only(LimitsWidget.name).include(LimitsWidget.maker)

    with pytest.raises(SnakeUnsupportedFeature) as error:
        query.to_include_sql(_POSTGRES)

    assert "only()/defer()" in str(error.value), (
        f"the refusal has to say WHAT it is refusing, not merely that it refuses: {error.value}"
    )


def _check_annotate_validates_the_model_at_runtime() -> None:
    """A query of another model than the `@snake_result` declares blows up when the plan is built."""
    with pytest.raises(SnakeEmitError, match="they do not match"):
        plan_annotate(
            SnakeQuery(LimitsWidget),
            LimitsTotals,
            _POSTGRES,
            {"total": sum_(LimitsWidget.id)},
        )


def _check_a_check_constraint_refuses_a_subquery() -> None:
    """A CHECK carrying an `IN (SELECT ...)` is rejected AT DECLARATION, not when migrating."""
    subquery = (
        SnakeQuery(LimitsMaker)
        .filter(LimitsMaker.name == "x")
        .as_scalar(LimitsMaker.id)
    )

    with pytest.raises(SnakeModelDefinitionError, match="subquery"):
        snake_check(LimitsWidget.maker_id.in_(subquery))

    snake_check(LimitsWidget.id > 0)  # and a plain one still goes through


def _check_in_does_not_chunk() -> None:
    """`in_()` emits one placeholder per value, well past the engine's bind-parameter ceiling."""
    values = list(range(70_000))
    _, params = (
        SnakeQuery(LimitsWidget).filter(LimitsWidget.id.in_(values)).to_sql(_POSTGRES)
    )

    assert len(params) == len(values) > _POSTGRES.max_bind_params
    assert _SQLITE.max_bind_params == 32_766
    assert _POSTGRES.max_bind_params == _MYSQL.max_bind_params == 65_535


def _check_a_composite_in_guards_only_the_exact_ceiling() -> None:
    """The placeholder ceiling refuses; the number of KEYS, on its own, does not.

    Both halves of the claim, because the page makes two. Going past `bind_params` raises with the
    two numbers in the message. Eight thousand keys of two columns is well past where PostgreSQL 17
    was measured to stop —`stack depth limit exceeded`, the parser's recursion and not the
    protocol's 65.535— and the ORM still emits it: that limit moves with the server's
    `max_stack_depth`, so refusing at a figure copied from one configuration would forbid on a tuned
    server what the database there allows.
    """
    columns: tuple[SnakeValue[object], ...] = (
        SnakeExpr(path=("a",)),
        SnakeExpr(path=("b",)),
    )
    over = SnakeTupleIn(
        columns=columns, rows=tuple((1, 2) for _ in range(_SQLITE.max_bind_params))
    )

    with pytest.raises(SnakeEmitError, match="placeholders"):
        emit_condition(over, _SQLITE)

    sql, params = emit_condition(
        SnakeTupleIn(columns=columns, rows=tuple((1, 2) for _ in range(8_000))),
        _POSTGRES,
    )
    assert len(params) == 16_000, (
        "the keys past Postgres's parser ceiling were not emitted"
    )
    assert sql.startswith("(")


def _check_bulk_writes_warn_instead_of_firing_signals(session: SnakeSession) -> None:
    """A bulk UPDATE leaves the handler unrun and says so out loud, naming model and signal.

    THE HANDLER IS CONNECTED HERE AND NOT AT IMPORT TIME, which is a bug that was paid for rather
    than a matter of taste. `_HANDLERS` is a GLOBAL dictionary and `src/test/session/` empties it
    with `disconnect_all()`; connected at import, this handler was already gone by the time the
    full suite reached this file, so the contrast below —that a plain `add()` DOES fire— failed.
    Only in the whole run, never in this file on its own, and far from the test that cleared it.
    Wiring it inside the test bets on no execution order at all.
    """
    fired: list[str] = []

    def record(instance: LimitsAudited) -> None:
        """Records the write, so "the signal did not fire" is measured rather than believed."""
        fired.append(instance.name)

    connect(LimitsAudited, SnakeSignal.PRE_SAVE, record)
    try:
        session.add(LimitsAudited(name="before"))
        session.commit()
        assert fired == ["before"], (
            "a plain add() DOES fire the signal; that is the contrast"
        )
        fired.clear()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            session.update_where(
                SnakeQuery(LimitsAudited).filter(LimitsAudited.name == "before"),
                [(LimitsAudited.name, "after")],
            )

        assert fired == [], "the page says a bulk write fires nothing; the handler ran"
        complaints = [
            str(warning.message)
            for warning in caught
            if issubclass(warning.category, SnakeWarning)
            and "LimitsAudited" in str(warning.message)
        ]
        assert complaints, (
            f"the silence has to be announced; nothing was warned: {caught}"
        )
        assert "pre_save" in complaints[0], (
            f"the warning has to name the signals that will not run: {complaints[0]}"
        )
    finally:
        # THIS model's handlers and nobody else's. A bare `disconnect_all()` would empty the whole
        # dictionary and do to the next file exactly what was done to this one.
        disconnect_all(LimitsAudited)


def _check_json_storage_offers_an_exact_alternative() -> None:
    """The escape hatch the JSONB entry promises is real: `JSON` maps to `json`, not to `jsonb`.

    HALF THE CLAIM, and it is said out loud rather than glossed over: the NORMALISATION itself is
    Postgres's behaviour and takes a Postgres to observe. What is checked without one is the part
    the ORM owns — that the way out the entry points at leads somewhere, since an entry offering a
    remedy that does not work is worse than the limitation it describes.
    """
    assert (
        _POSTGRES.map_type(dict, False, SnakeJsonParams(storage=SnakeJsonStorage.JSON))
        == "JSON"
    )
    assert (
        _POSTGRES.map_type(dict, False, SnakeJsonParams(storage=SnakeJsonStorage.JSONB))
        == "JSONB"
    )


def _check_json_get_takes_four_types() -> None:
    """`str`/`int`/`float`/`bool` go through; a `Decimal` and a `datetime` are refused by name."""
    for accepted in (str, int, float, bool):
        LimitsWidget.payload.json_get("k", as_type=accepted)

    for refused in (decimal.Decimal, datetime):
        with pytest.raises(SnakeUnsupportedFeature, match="json_get"):
            LimitsWidget.payload.json_get("k", as_type=refused)


def _check_a_json_key_is_a_plain_identifier() -> None:
    """A key with a space or a dot is a `SnakeValueError`: it is emitted inside the statement."""
    LimitsWidget.payload.json_get("owner", "name", as_type=str)

    for bad in ("a b", "a.b", "a'b"):
        with pytest.raises(SnakeValueError, match="plain identifier"):
            LimitsWidget.payload.json_get(bad, as_type=str)


def _check_an_int_defaults_to_sixty_four_bits() -> None:
    """A bare `int` is a `BIGINT`, a value past its range is refused, and `scale` is refused too.

    Both refusals go through the guards rather than through a driver on purpose: they are the point
    of the entry. SQLite collapses every integer into one width and ignores a declared scale, so
    leaving either to the engine would mean the model saying different things depending on where it
    runs — green in development, rejected on Postgres.
    """
    assert _POSTGRES.map_type(int) == _MYSQL.map_type(int) == "BIGINT"
    assert SnakeIntSize.BIGINT.value == "BIGINT"
    assert _POSTGRES.map_type(decimal.Decimal) == "NUMERIC", (
        "the way past the 64-bit ceiling the page names is `Decimal`, mapped to arbitrary precision"
    )

    table = snake_table(LimitsWidget)
    with pytest.raises(SnakeValueError, match="BIGINT"):
        _guard_declared_limits(table, {"id": 2**63})
    _guard_declared_limits(table, {"id": 2**63 - 1})

    with pytest.raises(SnakeValueError, match="decimal"):
        _guard_declared_limits(table, {"price": decimal.Decimal("1.2345")})
    _guard_declared_limits(table, {"price": decimal.Decimal("1.23")})


def _check_a_datetime_has_to_pick_its_shape() -> None:
    """A bare `snake_column()` over a `datetime` is refused at IMPORT time, naming both spellings."""
    with pytest.raises(SnakeModelDefinitionError) as error:

        @snake_model(table="limits_shapeless")
        class Shapeless(SnakeModel):
            """A date that never says whether it is an instant or a wall clock."""

            id: SnakeColumn[int] = snake_auto()
            when: SnakeColumn[datetime] = snake_column()

    assert "snake_datetime" in str(error.value) and "snake_datetimetz" in str(
        error.value
    )
    assert (
        _POSTGRES.map_type(datetime, False, SnakeDateTimeParams(tz=False))
        == "TIMESTAMP"
    )
    assert (
        _POSTGRES.map_type(SnakeUtc, False, SnakeDateTimeParams(tz=True))
        == "TIMESTAMPTZ"
    )


def _check_a_timestamptz_only_accepts_utc(session: SnakeSession) -> None:
    """An offset other than UTC is refused on write, and so is a naive value; UTC goes in."""
    session.add(LimitsMaker(name="m"))
    madrid = timezone(timedelta(hours=2))

    # The checker already refuses these two values — `SnakeUtc` cannot be built outside UTC — and
    # that is the FIRST net, not this one. What is under test is the runtime guard behind it, for
    # whoever arrives through `Any` or with the checker switched off, so the ignores are the point.
    with pytest.raises(SnakeValueError, match="only accepts UTC"):
        session.add(
            LimitsWidget(
                name="w",
                ratio=1.0,
                payload={},
                price=None,
                instant=datetime(2024, 1, 1, 14, 30, tzinfo=madrid),  # type: ignore[arg-type]
                wall=None,
                maker_id=1,
            )
        )

    with pytest.raises(SnakeValueError, match="WALL-CLOCK"):
        session.add(
            LimitsWidget(
                name="w",
                ratio=1.0,
                payload={},
                price=None,
                instant=None,
                wall=datetime(2024, 1, 1, 14, 30, tzinfo=madrid),
                maker_id=1,
            )
        )


def _check_sqlite_has_no_named_schemas() -> None:
    """`Cap.SCHEMAS` is `Nope`, and `schema=` disappears from the emitted DDL instead of failing."""
    assert isinstance(_SQLITE.capabilities.support_for(Cap.SCHEMAS), Nope)

    table = _probe_table(_probe_column())
    assert "app" not in emit_create_table(table, _SQLITE)
    assert '"app"."limits_probe"' in emit_create_table(table, _POSTGRES)


def _check_sqlite_cannot_add_a_constraint() -> None:
    """BOTH outcomes: the diff REBUILDS, and only a hand-written operation still stops.

    The page used to say the ORM stops, flat out, and half of it stopped being true the day
    `RebuildTable` arrived: when a table's only change is its constraints, `diff_schema` collapses it
    into one rebuild and SQLite spells the whole thing out. What still stops is the plan somebody
    writes by hand, which is the half worth publishing — so both are checked here.
    """
    assert isinstance(_SQLITE.capabilities.support_for(Cap.ADD_CONSTRAINT), Nope)

    unique = SnakeColumnInfo(name="code", python_type=int, unique=True)
    assert "UNIQUE" in emit_create_table(_probe_table(unique), _SQLITE)

    before = _probe_table(_probe_column())
    check = SnakeCheckInfo(
        condition=SnakeExpr(("code",), int) > 0, name="ck_limits_probe_code"
    )
    after = dataclasses.replace(before, checks=(check,))
    plan = realize(diff_schema([before], [after]), _SQLITE)
    assert [type(operation).__name__ for operation in plan] == ["RebuildTable"]
    rebuild = plan[0]
    assert isinstance(rebuild, RebuildTable)

    statements = rebuild.up_sql(_SQLITE)
    assert statements[0] == "PRAGMA defer_foreign_keys = ON"
    assert any(statement.startswith("INSERT INTO") for statement in statements)
    assert any(statement.startswith("DROP TABLE") for statement in statements)
    assert any("RENAME TO" in statement for statement in statements)

    # And the other half: written by hand, the same change is refused.
    with pytest.raises(SnakeMigrationError, match="AddCheck"):
        realize([AddCheck(table=after, check=check)], _SQLITE)


def _check_sqlite_cannot_drop_a_column_a_key_holds() -> None:
    """`Cap.DROP_COLUMN_CASCADES_FK` is `Nope`, and here the `DropForeignKey` route is shut too.

    That second half is what separates this engine from MySQL and why the page says it: putting the
    key's drop in front unblocks MySQL and stops on SQLite, which has no `DROP CONSTRAINT` either.
    """
    assert isinstance(
        _SQLITE.capabilities.support_for(Cap.DROP_COLUMN_CASCADES_FK), Nope
    )
    table = snake_table(LimitsWidget)
    column = next(one for one in table.columns if one.name == "maker_id")
    relationship = next(
        one for one in table.relationships if one.kind is SnakeRelationshipKind.TO_ONE
    )

    with pytest.raises(SnakeMigrationError, match="maker_id"):
        realize([DropColumn(table=table, column=column)], _SQLITE)
    with pytest.raises(SnakeMigrationError, match="ADD CONSTRAINT"):
        realize(
            [
                DropForeignKey(
                    table=table,
                    relationship=relationship,
                    target=snake_table(LimitsMaker),
                )
            ],
            _SQLITE,
        )


def _check_mysql_has_no_partial_indexes() -> None:
    """One `Nope`, two destinations: a search index is DEGRADED and a unique one STOPS."""
    assert isinstance(_MYSQL.capabilities.support_for(Cap.PARTIAL_INDEXES), Nope)

    email = SnakeColumnInfo(name="email", python_type=str)
    deleted = SnakeColumnInfo(name="deleted", python_type=int)
    table = SnakeTableInfo(
        name="limits_probe",
        columns=(email, deleted),
        primary_key=SnakePrimaryKeyInfo(columns=(email,)),
    )
    where = SnakeExpr(("deleted",), int) == 0
    search = SnakeIndexInfo(columns=("email",), where=where, name="ix_probe_email")
    unique = SnakeIndexInfo(
        columns=("email",), unique=True, where=where, name="uq_probe_email"
    )

    assert "WHERE" not in emit_create_index(table, search, _MYSQL)
    assert "WHERE" in emit_create_index(table, search, _POSTGRES)
    with pytest.raises(SnakeMigrationError, match="uq_probe_email"):
        realize([CreateIndex(table=table, index=unique)], _MYSQL)
    assert realize([CreateIndex(table=table, index=unique)], _POSTGRES)


def _check_mysql_cannot_drop_a_column_a_key_holds() -> None:
    """`Cap.DROP_COLUMN_CASCADES_FK` is `Nope`, and a `DropForeignKey` in front is the way out."""
    assert isinstance(
        _MYSQL.capabilities.support_for(Cap.DROP_COLUMN_CASCADES_FK), Nope
    )
    table = snake_table(LimitsWidget)
    column = next(one for one in table.columns if one.name == "maker_id")
    relationship = next(
        one for one in table.relationships if one.kind is SnakeRelationshipKind.TO_ONE
    )

    with pytest.raises(SnakeMigrationError, match="maker_id"):
        realize([DropColumn(table=table, column=column)], _MYSQL)
    assert realize(
        [
            DropForeignKey(
                table=table, relationship=relationship, target=snake_table(LimitsMaker)
            ),
            DropColumn(table=table, column=column),
        ],
        _MYSQL,
    )
    # Postgres takes the naked drop: the constraint falls with the column, so nothing guards it.
    assert realize([DropColumn(table=table, column=column)], _POSTGRES)


def _check_a_rebuild_only_carries_a_pure_constraint_change() -> None:
    """The collapse needs the constraints to be the ONLY difference, and the pair is checked.

    The second half of the page's claim —that a rebuild is not enough when another table's key names
    the one being remade— is a verdict the SQLite server hands down at `COMMIT`, so it is exercised
    against a real engine in `src/test/migration/test_rebuild_table.py` rather than here.
    """
    before = _probe_table(_probe_column())
    check = SnakeCheckInfo(
        condition=SnakeExpr(("code",), int) > 0, name="ck_limits_probe_code"
    )
    widened = dataclasses.replace(
        before,
        checks=(check,),
        columns=(*before.columns, SnakeColumnInfo(name="extra", python_type=int)),
    )

    # A column moved too, so the diff does NOT collapse it.
    assert [type(one).__name__ for one in diff_schema([before], [widened])] != [
        "RebuildTable"
    ]
    with pytest.raises(SnakeMigrationError, match="columns"):
        RebuildTable(before, widened)


def _check_sqlite_cannot_alter_a_column() -> None:
    """`Cap.ALTER_COLUMN` is `Nope`, and the PLAN is where an `AlterColumn` stops."""
    assert isinstance(_SQLITE.capabilities.support_for(Cap.ALTER_COLUMN), Nope)

    old = _probe_column()
    new = SnakeColumnInfo(name="code", python_type=str)
    with pytest.raises(SnakeMigrationError, match="AlterColumn"):
        realize([AlterColumn(table=_probe_table(old), old=old, new=new)], _SQLITE)


def _check_sqlite_has_no_replace_view_and_no_stored_functions() -> None:
    """One is REWRITTEN into drop + create, the other stops the plan. Two capabilities, two fates."""
    assert isinstance(_SQLITE.capabilities.support_for(Cap.REPLACE_VIEW), Nope)
    assert isinstance(_SQLITE.capabilities.support_for(Cap.STORED_FUNCTIONS), Nope)
    assert _SQLITE.capabilities.can(Cap.REPLACE_VIEW) is False


def _check_sqlite_skips_comments() -> None:
    """Two doors and two different fates, which is what the entry now says: dropped, then refused.

    The page used to say "skipped, not rejected" flat out, and half of it was false — this check
    found it. A `CreateTable` carrying `db_comment` is indeed skipped, and an `AlterTableComment`
    stops in the plan, because on an engine that stores no comment there is nothing to change.
    """
    assert isinstance(_SQLITE.capabilities.support_for(Cap.COMMENTS), Nope)
    table = _probe_table(_probe_column())

    assert emit_comments(table, _SQLITE) == []
    assert realize([CreateTable(table=table)], _SQLITE)  # skipped, not refused
    with pytest.raises(SnakeMigrationError, match="AlterTableComment"):
        realize([AlterTableComment(table=table, previous=None)], _SQLITE)


def _check_sqlite_has_no_row_locking() -> None:
    """`Cap.ROW_LOCKING` is `Nope`: there is no `SELECT ... FOR UPDATE` to emit."""
    assert isinstance(_SQLITE.capabilities.support_for(Cap.ROW_LOCKING), Nope)
    assert _SQLITE.supports_row_locking is False


def _check_sqlite_stores_no_sizes() -> None:
    """The three int widths collapse into `INTEGER` and the three string shapes into `TEXT`."""
    widths = {
        _SQLITE.map_type(int, False, SnakeIntParams(size=size)) for size in SnakeIntSize
    }
    assert widths == {"INTEGER"}

    assert _SQLITE.map_type(str) == "TEXT"
    assert _SQLITE.map_type(str, False, SnakeStrParams(max_length=50)) == "TEXT"
    assert (
        _SQLITE.map_type(str, False, SnakeStrParams(max_length=10, fixed=True))
        == "TEXT"
    )
    assert _SQLITE.max_numeric_precision is None and _SQLITE.max_numeric_scale is None


def _check_sqlite_orders_a_decimal_as_text() -> None:
    """A `Decimal` is stored as `TEXT`, which is exactly why `Cap.DECIMAL_ORDERING` is `Degraded`."""
    assert _SQLITE.map_type(decimal.Decimal) == "TEXT"
    assert _SQLITE.map_type(
        decimal.Decimal, False, SnakeDecimalParams(precision=12, scale=2)
    ) == ("TEXT")
    assert isinstance(_SQLITE.capabilities.support_for(Cap.DECIMAL_ORDERING), Degraded)


def _check_sqlite_has_no_arrays() -> None:
    """A `list[T]` lands in a `TEXT` column and `Cap.ARRAYS` is `Degraded`, never `Nope`."""
    assert _SQLITE.map_type(list[int]) == "TEXT"
    assert isinstance(_SQLITE.capabilities.support_for(Cap.ARRAYS), Degraded)
    assert _POSTGRES.map_type(list[int]) == "BIGINT[]"


def _check_sqlite_loses_a_nan(session: SnakeSession) -> None:
    """A NaN written to SQLite comes back `None`; the infinities come back whole."""
    session.add(LimitsMaker(name="m"))
    for name, value in (
        ("nan", float("nan")),
        ("inf", float("inf")),
        ("-inf", float("-inf")),
    ):
        session.add(
            LimitsWidget(
                name=name,
                ratio=value,
                payload={},
                price=None,
                instant=None,
                wall=None,
                maker_id=1,
            )
        )
    session.commit()

    stored = {
        widget.name: widget.ratio for widget in session.all(SnakeQuery(LimitsWidget))
    }
    assert stored["nan"] is None, (
        "SQLite cannot store a NaN; the page says it comes back NULL"
    )
    assert stored["inf"] == float("inf") and stored["-inf"] == float("-inf")
    assert isinstance(_SQLITE.capabilities.support_for(Cap.FLOAT_SPECIALS), Degraded)


def _check_sqlite_refuses_a_timeout_wrap() -> None:
    """`statement_timeout_sql` is `None` and `TimeoutDriver` refuses the wrap rather than faking it."""
    assert _SQLITE.statement_timeout_sql(1000) is None

    driver = SQLiteDriver.connect(":memory:")
    try:
        with pytest.raises(SnakeDialectError, match="statement timeout"):
            TimeoutDriver(driver, _SQLITE, statement_timeout_ms=1000)
    finally:
        driver.close()


def _check_mysql_has_no_returning() -> None:
    """`Cap.RETURNING` is `Nope`, the flag agrees, and the required-value guard names the column.

    What a live MySQL would add is that the rows DO get inserted with the ids left empty. The part
    that can be run here is the whole decision surface: the branch the page tells you to take
    (`session.dialect.supports_returning`) and the guard that catches the id which never came back.
    """
    assert isinstance(_MYSQL.capabilities.support_for(Cap.RETURNING), Nope)
    assert _MYSQL.supports_returning is False
    assert _POSTGRES.supports_returning is True and _SQLITE.supports_returning is True

    with pytest.raises(SnakeValueError, match="id never came back"):
        _guard_required_values(
            snake_table(LimitsWidget), {"name": MISSING, "maker_id": 1}
        )


def _check_mysql_has_no_native_instant() -> None:
    """A `SnakeUtc` falls back to `TEXT`; a wall clock is native and honours its precision."""
    assert _MYSQL.map_type(SnakeUtc, False, SnakeDateTimeParams(tz=True)) == "TEXT"
    assert isinstance(_MYSQL.capabilities.support_for(Cap.TIMESTAMPTZ), Degraded)

    assert _MYSQL.map_type(
        datetime, False, SnakeDateTimeParams(tz=False, precision=3)
    ) == ("DATETIME(3)")
    assert _MYSQL.max_fractional_seconds == 6
    with pytest.raises(SnakeDialectError, match="fractional-second"):
        _MYSQL.map_type(datetime, False, SnakeDateTimeParams(tz=False, precision=9))


def _check_mysql_demands_a_declared_precision() -> None:
    """A bare `Decimal` is REFUSED on MySQL and lossless on Postgres — which is why it is refused."""
    with pytest.raises(SnakeDialectError, match="unbounded DECIMAL"):
        _MYSQL.map_type(decimal.Decimal)

    assert _MYSQL.map_type(
        decimal.Decimal, False, SnakeDecimalParams(precision=10, scale=2)
    ) == ("DECIMAL(10,2)")
    assert _POSTGRES.map_type(decimal.Decimal) == "NUMERIC"


def _check_mysql_decimal_has_two_ceilings() -> None:
    """65 digits and 30 decimals, and they are SEPARATE: `DECIMAL(40,35)` breaks only the second."""
    assert _MYSQL.max_numeric_precision == 65 and _MYSQL.max_numeric_scale == 30

    with pytest.raises(SnakeDialectError, match="65 digits"):
        _MYSQL.map_type(
            decimal.Decimal, False, SnakeDecimalParams(precision=500, scale=2)
        )
    with pytest.raises(SnakeDialectError, match="30 decimal"):
        _MYSQL.map_type(
            decimal.Decimal, False, SnakeDecimalParams(precision=40, scale=35)
        )

    assert (
        _POSTGRES.map_type(
            decimal.Decimal, False, SnakeDecimalParams(precision=500, scale=2)
        )
        == "NUMERIC(500,2)"
    )


def _check_mysql_stores_a_timedelta_and_a_list_as_text() -> None:
    """Neither is refused: both fall back to `TEXT`, declared `Degraded`. And two round-trip types."""
    assert _MYSQL.map_type(timedelta) == "TEXT"
    assert _MYSQL.map_type(list[int]) == "TEXT"
    assert isinstance(_MYSQL.capabilities.support_for(Cap.INTERVAL), Degraded)
    assert isinstance(_MYSQL.capabilities.support_for(Cap.ARRAYS), Degraded)
    assert _MYSQL.map_type(bool) == "TINYINT(1)"
    assert _MYSQL.map_type(uuid.UUID) == "CHAR(36)"


def _check_mysql_ddl_is_not_transactional() -> None:
    """`Cap.TRANSACTIONAL_DDL` is `Nope` on MySQL and `Full` on the two engines that have it."""
    assert isinstance(_MYSQL.capabilities.support_for(Cap.TRANSACTIONAL_DDL), Nope)
    assert _MYSQL.supports_transactional_ddl is False
    assert _POSTGRES.supports_transactional_ddl and _SQLITE.supports_transactional_ddl


def _check_mysql_has_no_named_schemas() -> None:
    """`Cap.SCHEMAS` is `Nope`, and the qualified name never reaches the DDL."""
    assert isinstance(_MYSQL.capabilities.support_for(Cap.SCHEMAS), Nope)
    assert "app" not in emit_create_table(_probe_table(_probe_column()), _MYSQL)


def _check_mysql_comments_are_a_clause_and_a_column_costs_a_rewrite() -> None:
    """The entry this check used to certify said the ORM emitted no comment at all on MySQL.

    It was true of the ORM and false of the engine, and the docstring here said so out loud —
    "THE PAGE SAYS MySQL comments inline. The engine does; this ORM does not emit them at all" —
    while asserting the ORM's side. That is the shape of a check that ratifies a gap instead of
    reporting it. Measured against MariaDB 11.8.8, both comments are stored and read back.

    So the two halves the entry now claims: the comment TRAVELS (inline, in the CREATE TABLE), and
    a COLUMN comment costs a `MODIFY COLUMN` carrying the whole definition, which is what makes the
    capability `Degraded` rather than `Full`.
    """
    support = _MYSQL.capabilities.support_for(Cap.COMMENTS)
    assert isinstance(support, Degraded)
    assert "MODIFY COLUMN" in support.reason

    column = dataclasses.replace(_probe_column(), db_comment="a column note")
    table = dataclasses.replace(
        _probe_table(column), columns=(column,), db_comment="a table note"
    )
    created = emit_create_table(table, _MYSQL)

    assert created.endswith("COMMENT = 'a table note'")
    assert "COMMENT 'a column note'" in created
    assert "COMMENT ON" not in created
    assert (
        emit_comments(table, _MYSQL) == []
    )  # they already travelled inside the CREATE
    assert emit_column_comment(table, column, _MYSQL).startswith(
        "ALTER TABLE `limits_probe` MODIFY COLUMN"
    )


def _check_mysql_timeout_is_the_mariadb_variable() -> None:
    """The statement it emits is `SET SESSION max_statement_time`, which is MariaDB's spelling."""
    emitted = _MYSQL.statement_timeout_sql(1500)

    assert emitted is not None and emitted.startswith("SET SESSION max_statement_time")


def _check_introspection_is_not_bijective() -> None:
    """Three SQL spellings of a string come back as one Python type, on both catalogues."""
    assert {
        _sqlite_python_type(declared)
        for declared in ("TEXT", "VARCHAR(50)", "CHAR(10)")
    } == {str}
    assert {
        _POSTGRES_PYTHON_TYPES[name]
        for name in ("text", "character varying", "character")
    } == {str}


def _check_introspection_warns_about_what_it_cannot_represent() -> None:
    """The four kinds the page names produce a WARNING TEXT rather than a piece of metadata."""
    assert "trigger" in trigger_warning("t_audit", "orders")
    assert "routine" in routine_warning("calc_payroll")
    assert "expression index" in expression_index_warning("idx_lower_name")
    assert "no equivalent" in unrepresentable_column_warning(
        "orders", "geom", "geometry"
    )


def _check_a_rename_is_only_suggested() -> None:
    """The diff produces a drop plus an add; the rename is a HINT on the console, never an operation."""
    table = _probe_table(_probe_column())
    old = SnakeColumnInfo(name="old_name", python_type=str)
    new = SnakeColumnInfo(name="new_name", python_type=str)
    operations: list[SnakeMigrationOperation] = [
        DropColumn(table=table, column=old),
        AddColumn(table=table, column=new),
    ]

    suggestions = rename_suggestions(operations)
    assert suggestions == [("limits_probe", "old_name", "new_name")]
    hint = format_rename_hint(suggestions)
    assert "RenameColumn" in hint and "could be a RENAME" in hint


def _check_a_squash_stops_where_it_cannot_replay() -> None:
    """A squash stops at a DATA operation it would have to EXECUTE in order to collapse.

    The page used to claim it stopped over a PARTIALLY-APPLIED history, and this check is what
    showed it could not: `squash()` takes a `Sequence[Migration]` and nothing else — no driver, no
    session — so it cannot know what is applied. It was published as a promise the signature makes
    impossible to keep.
    """
    history = [Migration(version="0001_seed", operations=(RunSQL("SELECT 1"),))]

    with pytest.raises(SnakeMigrationError, match="DATA operation"):
        squash(history, version="0002_squashed")


def _check_a_squash_keeps_the_files_it_replaces() -> None:
    """The collapsed migration is written and the originals stay put, named in its `replaces`.

    Run through the CLI command rather than around it: what the entry promises is what a person
    gets from `snakeorm squash`, and `squash()` on its own writes no file at all — it could not
    delete one either, so calling it would prove nothing about the sentence.
    """
    column = SnakeColumnInfo(name="id", python_type=int)
    table = SnakeTableInfo(
        name="limits_squash_probe",
        columns=(column,),
        primary_key=SnakePrimaryKeyInfo(columns=(column,)),
    )

    with tempfile.TemporaryDirectory() as raw:
        directory = pathlib.Path(raw)
        (directory / "0001_one.py").write_text(
            render_migration("0001_one", [CreateTable(table=table)]), encoding="utf-8"
        )
        (directory / "0002_two.py").write_text(
            render_migration("0002_two", []), encoding="utf-8"
        )

        code = _cmd_squash(
            argparse.Namespace(
                dir=str(directory),
                database=DEFAULT_DATABASE,
                until="0002_two",
                name="collapsed",
            )
        )

        assert code == 0
        written = sorted(path.name for path in directory.glob("*.py"))
        assert written == ["0001_one.py", "0002_two.py", "0003_collapsed.py"], (
            f"the entry says the replaced files are kept; the directory holds {written}"
        )
        collapsed = (directory / "0003_collapsed.py").read_text(encoding="utf-8")
        assert "replaces" in collapsed and "0001_one" in collapsed, (
            "the collapsed migration has to NAME what it replaces, or a database that applied only "
            "some of the originals has no way to know it is covered"
        )


def _check_there_is_no_joined_table_inheritance() -> None:
    """A child compiles into its base's table, and the metadata has nowhere to record another one.

    THE FIRST DRAFT OF THIS SCANNED THE PUBLIC NAMES for the word "joined", and it went red on
    `SnakeJoinedQuery` — an explicit JOIN onto a collection, a different thing entirely. That is
    the blacklist failing the other way round, and widening the word list would have been the
    `test_strings_are_english` mistake with the calendar reset. So it is anchored on STRUCTURE
    instead, which cannot be fooled by a name:

    - single-table inheritance IS the child sharing the base's `SnakeTableInfo`, its own columns
      included. Joined-table would give it a table of its own, joined by the primary key;
    - and `SnakePolymorphicInfo` carries a discriminator and a value, with no field naming a parent
      table to join to. Building the other strategy means growing one, and that turns this red.
    """
    base, child = snake_table(LimitsBeast), snake_table(LimitsDog)

    assert child.name == base.name, (
        f"the child has a table of its own ({child.name} vs {base.name}), which is joined-table "
        f"inheritance. The entry says it does not exist"
    )
    assert "breed" in {column.name for column in base.columns}, (
        "the child's own column lives in the BASE's table, which is what the single table means "
        "and what makes the NULL rule the price the entry names"
    )

    recorded = {field.name for field in dataclasses.fields(SnakePolymorphicInfo)}
    assert recorded == {"column", "value"}, (
        f"the polymorphic metadata grew past a discriminator and a value: {sorted(recorded)}. "
        f"Joining a child to its base needs a field naming the parent table, so a new one here is "
        f"the first thing the other strategy would need — and the entry would be false."
    )


def _check_distinct_on_is_not_emitted() -> None:
    """`distinct()` takes no columns and emits the plain `DISTINCT` on all three engines.

    The signature is the sharper half: `DISTINCT ON` needs the columns to be distinct BY, so it
    cannot be expressed through a method that accepts none. Adding the feature means changing this
    signature or adding a sibling, and both turn this red — which is the point of the entry.
    """
    assert list(inspect.signature(SnakeQuery.distinct).parameters) == ["self"], (
        "distinct() grew a parameter; DISTINCT ON is what a column list there would mean"
    )

    query = SnakeQuery(LimitsWidget).distinct()
    for dialect in (_POSTGRES, _MYSQL, _SQLITE):
        sql, _ = query.to_sql(dialect)
        assert "SELECT DISTINCT " in sql and "DISTINCT ON" not in sql, sql
    projected, _ = query.to_project_sql(_POSTGRES, [LimitsWidget.name])
    assert "SELECT DISTINCT " in projected and "DISTINCT ON" not in projected


def _check_the_autoincrement_toggle_spells_the_sequence_out() -> None:
    """Postgres emits what `BIGSERIAL` MEANS; MySQL carries it inline; SQLite stops at the plan."""
    plain, auto = _probe_column(), _probe_column(autoincrement=True)
    table = _probe_table(plain)

    postgres = " ".join(emit_alter_column(table, plain, auto, _POSTGRES))
    assert "CREATE SEQUENCE" in postgres
    assert "nextval" in postgres and "OWNED BY" in postgres and "setval" in postgres
    assert "BIGSERIAL" not in postgres, "BIGSERIAL is not a type; the server rejects it"

    assert "MODIFY COLUMN" in " ".join(emit_alter_column(table, plain, auto, _MYSQL))

    with pytest.raises(SnakeMigrationError, match="AlterColumn"):
        realize([AlterColumn(table=table, old=plain, new=auto)], _SQLITE)


def _check_runpython_without_backward_cannot_be_undone() -> None:
    """The rollback raises, and the message says what to add instead of failing blankly."""
    operation = RunPython(forward=_nothing)

    with pytest.raises(SnakeMigrationError, match="backward"):
        operation.unrun(None)  # type: ignore[arg-type]


def _check_the_async_runner_refuses_a_data_migration() -> None:
    """A `RunPython` handed to the asynchronous runner stops instead of being marked applied."""
    with pytest.raises(SnakeMigrationError, match="RunPython"):
        _reject_data_operation(RunPython(forward=_nothing))

    _reject_data_operation(CreateSchema(schema="app"))


def _check_a_polymorphic_child_column_must_be_nullable() -> None:
    """Declared `NOT NULL` on a child, it stops at DECLARATION and names the offending columns."""
    with pytest.raises(SnakeModelDefinitionError, match="accept NULL") as error:

        @snake_model(discriminator_value="cat")
        class LimitsCat(LimitsBeast):
            """A child whose own column refuses NULL, which its siblings' rows cannot honour."""

            lives: SnakeColumn[int] = snake_int()

    assert "lives" in str(error.value), (
        f"the refusal has to NAME the columns to fix, not merely announce the rule: {error.value}"
    )


def _check_a_type_checking_only_target_breaks_the_linker() -> None:
    """The linker evaluates the annotation at RUNTIME, so an import it cannot see is a `NameError`.

    Declared in a registry of its OWN: a model whose target never resolves would otherwise poison
    the global `snake_link()` for every test that runs after this one.
    """
    private = SnakeRegistry()

    @snake_model(table="limits_ghosts", registry=private)
    class LimitsGhost(SnakeModel):
        """Its target is spelled the way a `if TYPE_CHECKING:` import spells it: unresolvable."""

        id: SnakeColumn[int] = snake_auto()
        target_id: SnakeColumn[int] = snake_int()
        # Undefined ON PURPOSE, which is exactly the shape the page describes: a name the editor
        # resolves and the interpreter does not. mypy sees the same hole a `TYPE_CHECKING` import
        # would leave, and silencing it here is what keeps the case reproducible.
        target: SnakeToOne[LimitsAbsentTarget] = snake_to_one(  # type: ignore[name-defined] # noqa: F821
            target_id
        )

    with pytest.raises(NameError, match="LimitsAbsentTarget"):
        snake_link(private)


def _check_an_unknown_discriminator_hydrates_the_base(session: SnakeSession) -> None:
    """A row whose discriminator names no registered subclass comes back as the BASE, not lost."""
    session.add(LimitsDog(name="rex", breed="collie"))
    session.commit()
    # The discriminator is rewritten to a value no subclass claims, which is what a hierarchy that
    # lost a class —or a row written from outside the ORM— leaves behind in the table.
    session.update_where(
        SnakeQuery(LimitsBeast).filter(LimitsBeast.name == "rex"),
        [(LimitsBeast.kind, "wolf")],
    )
    session.commit()

    beast = session.first(SnakeQuery(LimitsBeast))

    assert beast is not None, "the row survives; what is lost is the subclass"
    assert type(beast) is LimitsBeast
    assert beast.name == "rex"


def _check_the_routine_name_is_validated_and_not_quoted() -> None:
    """Every dot-separated part is a plain identifier; the name comes back EXACTLY as written."""
    assert routine_name("public.CalculatePayroll") == "public.CalculatePayroll"
    assert routine_name("calc_$1") == "calc_$1"

    for bad in ("bad name", "1st", '"Mixed Case"', "drop;table"):
        with pytest.raises(SnakeValueError, match="valid routine name"):
            routine_name(bad)


def _check_the_session_exit_leaves_the_driver_open() -> None:
    """Leaving the `with` commits and does NOT close the driver; `close()` is what returns it."""
    driver = SQLiteDriver.connect(":memory:")
    try:
        with SnakeSession(driver, _SQLITE):
            pass
        driver.execute("SELECT 1", ())  # still usable: the session did not close it
    finally:
        driver.close()


def _check_postgres_timeout_is_not_set_local() -> None:
    """`SET`, which a rollback reverts, and not `SET LOCAL`. The page tells you to use the DSN."""
    emitted = _POSTGRES.statement_timeout_sql(1500)

    assert emitted == "SET statement_timeout = 1500"
    assert "LOCAL" not in emitted


def _check_there_is_no_identity_map(session: SnakeSession) -> None:
    """Two reads of the same row give two objects; equal by PK, not the same object."""
    session.add(LimitsMaker(name="m"))
    session.commit()

    first = session.first(SnakeQuery(LimitsMaker))
    second = session.first(SnakeQuery(LimitsMaker))

    assert first is not None and second is not None
    assert first == second and first is not second


def _check_there_is_no_lazy_loading(session: SnakeSession) -> None:
    """Touching a relation nobody included RAISES; there is no query behind the attribute."""
    session.add(LimitsMaker(name="m"))
    session.add(
        LimitsWidget(
            name="w",
            ratio=1.0,
            payload={},
            price=None,
            instant=None,
            wall=None,
            maker_id=1,
        )
    )
    session.commit()

    widget = session.first(SnakeQuery(LimitsWidget))
    assert widget is not None
    with pytest.raises(SnakeRelationshipNotLoaded, match="was not loaded"):
        _ = widget.maker


def _check_there_is_no_full_text_api() -> None:
    """No public symbol offers one, and `raw` — the way the page points at — does exist."""
    import snakeorm

    named = [
        name
        for name in dir(snakeorm)
        if not name.startswith("_")
        and any(
            word in name.lower()
            for word in ("fulltext", "full_text", "tsvector", "tsquery")
        )
    ]

    assert named == [], (
        f"the page says there is no typed full-text API and these appeared: {named}"
    )
    assert callable(SnakeSession.raw) and callable(AsyncSession.raw)


def _check_there_is_no_json_containment_api() -> None:
    """`json_get` reads a key; nothing offers containment or a path predicate."""
    import snakeorm

    named = [
        name
        for name in dir(snakeorm)
        if not name.startswith("_")
        and any(
            word in name.lower()
            for word in ("json_contains", "containment", "json_path", "json_exists")
        )
    ]

    assert named == [], (
        f"the page says there is no containment API and these appeared: {named}"
    )
    assert callable(SnakeSession.raw)


def _check_there_is_no_array_operator_api() -> None:
    """A `list[T]` column round-trips; no public symbol queries INSIDE one."""
    import snakeorm

    named = [
        name
        for name in dir(snakeorm)
        if not name.startswith("_") and "array" in name.lower()
    ]

    assert named == [], (
        f"the page says there is no array operator API and these appeared: {named}"
    )


def _check_the_driver_exposes_no_server_notices() -> None:
    """Neither the Protocol nor the package offers a way to read them.

    The Protocol is the load-bearing half: it deliberately does not expose the cursor, and that is
    what lets one dialect serve every driver.
    """
    import snakeorm

    from snakeorm.drivers.base import SnakeDriver

    on_the_protocol = [
        name
        for name in dir(SnakeDriver)
        if not name.startswith("_")
        and any(word in name.lower() for word in ("notice", "statusmessage", "cursor"))
    ]
    in_the_package = [
        name
        for name in dir(snakeorm)
        if not name.startswith("_")
        and any(word in name.lower() for word in ("notice", "statusmessage"))
    ]

    assert on_the_protocol == [], f"the driver Protocol grew: {on_the_protocol}"
    assert in_the_package == [], f"the package grew: {in_the_package}"


def _check_there_is_no_error_page_channel() -> None:
    """The five debug channels are the five there are; none of them serves an error page."""
    from snakeorm.debug import SnakeDebugChannel

    names = sorted(channel.name for channel in SnakeDebugChannel)

    assert names == ["ENVELOPE", "OTEL", "SIDECAR", "SSR", "TIMING"], (
        f"the channel catalogue changed: {names}"
    )


def _check_there_are_exactly_three_engines() -> None:
    """Three dialects, three synchronous drivers, three asynchronous ones. No fourth, anywhere."""
    import snakeorm

    dialects = {
        name
        for name in dir(snakeorm)
        if name.endswith("Dialect") and not name.startswith("Snake")
    }

    assert dialects == {"PostgresDialect", "MySQLDialect", "SQLiteDialect"}
    for dialect in (_POSTGRES, _MYSQL, _SQLITE):
        assert dialect.capabilities.support_for(Cap.UPSERT) is not None


def _check_mysql_declares_no_stored_functions() -> None:
    """MySQL/MariaDB refuses stored functions, and says so with a reason of its own.

    The page says it for MySQL as well as for SQLite, and the two reasons are different — SQLite's
    functions are registered from the process that opens the connection, MySQL's problem is that one
    dialect serves two forks that disagree about `CREATE OR REPLACE FUNCTION`. Asserting the reason
    and not just the refusal is what keeps the page from flattening them into one.
    """
    from snakeorm.dialects import MySQLDialect
    from snakeorm.dialects.capabilities import Cap, Nope

    answer = MySQLDialect().capabilities.support_for(Cap.STORED_FUNCTIONS)

    # `isinstance` and not a name comparison: the name would read the same to a human and tells the
    # checker nothing, so `answer.reason` on the next line would be an unnarrowed union access.
    assert isinstance(answer, Nope), answer
    assert "CREATE OR REPLACE FUNCTION" in answer.reason


_CHECKS: dict[str, Callable[[], None]] = {
    "No stored functions either.": _check_mysql_declares_no_stored_functions,
    "`==` over a class expression returns `SnakeCondition`, not `bool`.": (
        _check_equality_is_a_condition
    ),
    "The `field_specifiers` tuple is duplicated five times.": (
        _check_field_specifiers_are_duplicated_five_times
    ),
    "Streaming doesn't coexist with a to-many `include()`.": (
        _check_streaming_refuses_a_to_many_include
    ),
    "`only()`/`defer()` do not combine with `include()`.": _check_only_does_not_combine_with_include,
    "`annotate` validates at runtime": _check_annotate_validates_the_model_at_runtime,
    "CHECKs don't allow subqueries": _check_a_check_constraint_refuses_a_subquery,
    "`in_()` does not chunk by the bind-parameter ceiling.": _check_in_does_not_chunk,
    "A composite `IN` has TWO ceilings, and the ORM only guards the one it can know exactly.": (
        _check_a_composite_in_guards_only_the_exact_ceiling
    ),
    "A `dict` in `JSONB` gets NORMALIZED.": _check_json_storage_offers_an_exact_alternative,
    "`json_get(as_type=...)` only takes `str`, `int`, `float` or `bool`.": (
        _check_json_get_takes_four_types
    ),
    "A JSON key has to be a plain identifier.": _check_a_json_key_is_a_plain_identifier,
    "An `int` larger than ±9.2·10¹⁸ doesn't fit.": _check_an_int_defaults_to_sixty_four_bits,
    "A `datetime` column has no default shape: you pick it.": (
        _check_a_datetime_has_to_pick_its_shape
    ),
    "No named schemas.": _check_sqlite_has_no_named_schemas,
    "No `ALTER TABLE ADD CONSTRAINT`, and there are two outcomes, not one.": (
        _check_sqlite_cannot_add_a_constraint
    ),
    "Rebuilding is the only way to drop a column a foreign key still holds.": (
        _check_sqlite_cannot_drop_a_column_a_key_holds
    ),
    "No `ALTER COLUMN`.": _check_sqlite_cannot_alter_a_column,
    "No `CREATE OR REPLACE VIEW` or stored functions.": (
        _check_sqlite_has_no_replace_view_and_no_stored_functions
    ),
    "`COMMENT ON`s are dropped when creating, and refused when altering.": (
        _check_sqlite_skips_comments
    ),
    "No `SELECT ... FOR UPDATE`.": _check_sqlite_has_no_row_locking,
    "It doesn't store sizes or precision.": _check_sqlite_stores_no_sizes,
    "A `Decimal` is ordered as TEXT.": _check_sqlite_orders_a_decimal_as_text,
    "No arrays either.": _check_sqlite_has_no_arrays,
    "No server-side statement timeout.": _check_sqlite_refuses_a_timeout_wrap,
    "No `RETURNING`.": _check_mysql_has_no_returning,
    "No native instants: `snake_datetimetz()` falls back to TEXT.": (
        _check_mysql_has_no_native_instant
    ),
    "A `Decimal` has to declare its precision.": _check_mysql_demands_a_declared_precision,
    "A `DECIMAL` tops out at 65 digits and 30 decimals.": _check_mysql_decimal_has_two_ceilings,
    "No type for `timedelta` or arrays.": _check_mysql_stores_a_timedelta_and_a_list_as_text,
    "No partial indexes, and the same `Nope` has TWO destinations.": (
        _check_mysql_has_no_partial_indexes
    ),
    "Dropping the key first is what frees a column a foreign key still holds.": (
        _check_mysql_cannot_drop_a_column_a_key_holds
    ),
    "DDL isn't transactional.": _check_mysql_ddl_is_not_transactional,
    'A "schema" IS a database.': _check_mysql_has_no_named_schemas,
    "A comment is a clause, and changing a COLUMN's one rewrites the column.": (
        _check_mysql_comments_are_a_clause_and_a_column_costs_a_rewrite
    ),
    "`TimeoutDriver` emits `SET SESSION max_statement_time`": (
        _check_mysql_timeout_is_the_mariadb_variable
    ),
    "The round-trip isn't bijective.": _check_introspection_is_not_bijective,
    "What the ORM can't express is warned about, not represented.": (
        _check_introspection_warns_about_what_it_cannot_represent
    ),
    "Renames aren't detected on their own.": _check_a_rename_is_only_suggested,
    "A squash stops when it crosses a data migration.": (
        _check_a_squash_stops_where_it_cannot_replay
    ),
    "A squash does not delete the migrations it replaces, and that is deliberate.": (
        _check_a_squash_keeps_the_files_it_replaces
    ),
    "There is no joined-table inheritance, and it was DISCARDED rather than postponed.": (
        _check_there_is_no_joined_table_inheritance
    ),
    "`DISTINCT ON` is out of scope.": _check_distinct_on_is_not_emitted,
    "Toggling `int` ↔ autoincrement is emitted, and on Postgres it's the sequence spelled out.": (
        _check_the_autoincrement_toggle_spells_the_sequence_out
    ),
    "`RebuildTable` only collapses a PURE constraint change, and on SQLite it isn't always enough.": (
        _check_a_rebuild_only_carries_a_pure_constraint_change
    ),
    "`RunPython` without `backward` can't be undone.": (
        _check_runpython_without_backward_cannot_be_undone
    ),
    "The async runner doesn't run data migrations.": (
        _check_the_async_runner_refuses_a_data_migration
    ),
    "A child's own columns have to allow `NULL`.": (
        _check_a_polymorphic_child_column_must_be_nullable
    ),
    "The session's `__exit__` doesn't close the driver (by design).": (
        _check_the_session_exit_leaves_the_driver_open
    ),
    "On Postgres, `TimeoutDriver` sets `statement_timeout` with `SET`, not `SET LOCAL`.": (
        _check_postgres_timeout_is_not_set_local
    ),
    "A relation target only importable under `TYPE_CHECKING` breaks `snake_link()`.": (
        _check_a_type_checking_only_target_breaks_the_linker
    ),
    "The routine name of `call()` / `execute_procedure()` is validated, not quoted.": (
        _check_the_routine_name_is_validated_and_not_quoted
    ),
    "Full-text search.": _check_there_is_no_full_text_api,
    "JSON containment and path operators.": _check_there_is_no_json_containment_api,
    "Array operators.": _check_there_is_no_array_operator_api,
    "Server notices and `statusmessage`.": _check_the_driver_exposes_no_server_notices,
    "An error page of the ORM's own.": _check_there_is_no_error_page_channel,
    "Engines beyond PostgreSQL, MySQL/MariaDB and SQLite.": _check_there_are_exactly_three_engines,
}
"""Claim -> the code that runs it. Written by hand, one entry per bullet of the page."""


_SESSION_CHECKS: dict[str, Callable[[SnakeSession], None]] = {
    "A `TIMESTAMPTZ` column only accepts UTC.": _check_a_timestamptz_only_accepts_utc,
    "A NaN `float` comes back as `NULL`.": _check_sqlite_loses_a_nan,
    "An unknown discriminator is hydrated as the base class.": (
        _check_an_unknown_discriminator_hydrates_the_base
    ),
    "Bulk writes don't fire signals.": _check_bulk_writes_warn_instead_of_firing_signals,
    "Identity map.": _check_there_is_no_identity_map,
    "Lazy loading.": _check_there_is_no_lazy_loading,
}
"""The ones that need rows to exist. In-memory SQLite, so they need no server either."""


_NOT_EXECUTABLE: dict[str, str] = {
    "`session.select()` projects FOUR columns at most.": (
        "it is a claim about what a type CHECKER accepts and this file runs none — at runtime the "
        "implementation takes `*columns` and a fifth works fine, so asserting the runtime would "
        "assert the opposite sentence. The checker half lives in `src/test/typing/cases_negative.py`, "
        "which pins the `call-overload` under mypy AND pyright"
    ),
    "`type[Brand]` is callable.": (
        "it is a claim about what a type CHECKER accepts, and this file runs none. At runtime the "
        "class-access proxy is not callable at all, so asserting the runtime would be asserting "
        "the opposite sentence. The checker half belongs to src/test/typing/, which does run mypy "
        "and pyright over declared cases"
    ),
}
"""Claims NOT exercised, each with the reason it is not.

A gap written down is a gap somebody can close; a gap left out is one nobody can see. Striking one
off is the point of the work, and the guards below fail while an entry sits in both tables, so the
list cannot go on claiming a gap that was closed.
"""


def _covered() -> set[str]:
    """Every claim this file exercises, by either route."""
    return set(_CHECKS) | set(_SESSION_CHECKS)


# --------------------------------------------------------------------------------------------
# The guards. Both directions, plus the sanity probe every self-discovering check needs.
# --------------------------------------------------------------------------------------------


def test_the_page_is_there_and_still_full_of_claims() -> None:
    """The parse found the page and still recognises a bullet it must.

    The trap of every check that discovers its own input: over an EMPTY parse "nothing is missing"
    holds and both guards below turn into decoration. How much of the page is read is measured by
    the equality in the next test and not by a floor here — a floor set under the real number
    tolerates the difference in silence, which is what `>= 50` did while the page published 59.
    """
    claims = page_claims()

    assert _PAGE.exists(), f"{_PAGE} is gone; the whole file is measuring nothing"
    assert "Identity map." in claims, (
        "the anchor parse no longer recognises a bullet it must"
    )


@pytest.mark.parametrize("page", (_PAGE, _SPANISH_PAGE), ids=lambda page: page.name)
def test_every_bullet_of_the_page_is_a_claim_of_its_own(page: pathlib.Path) -> None:
    """Bullets opened, claims parsed, entries kept: the three counts of a page are ONE number.

    THE RULE THIS PUTS ON THE PAGE, and it is a real one: two bullets may not open with the same
    bold text. The anchor is the IDENTITY of a claim here — it is what `_CHECKS` types out and what
    both guards below match on — so a repeat is not a matter of style, it is two promises wearing
    one name, and only one of them can ever be answered for. It sounds like a rule nobody would
    break, and the page has come within a comma of breaking it twice: `:73` and `:135` differ only
    by a trailing clause, and splitting a MySQL bullet once nearly produced a second `No named
    schemas.` beside SQLite's. Both were avoided by WORDING, which is not a guard.

    ONE EQUALITY, TWO HOLES, and neither of them is hypothetical:

    - bullets != pairs is an anchoring regex that stopped matching. That is the same failure the
      floor this replaces was meant to catch and could not: `>= 50` over 59 published claims let
      nine of them fall off without a word;
    - pairs != claims is two bullets sharing an anchor. That one used to happen INSIDE the parser,
      which wrote into a dictionary and lost the second entry before any assertion existed to see
      it — the page could publish a claim that nothing ran, with everything green.

    Held over BOTH languages, because the collapse is in the parse and not in the prose: the Spanish
    page loses a duplicate in exactly the same way, and the per-section count that
    `test_the_two_languages_publish_the_same_limits` compares would go on matching while both pages
    hid one each.
    """
    assert page.exists(), f"{page} is gone; the whole file is measuring nothing"

    bullets = page_bullets(page)
    pairs = page_claim_pairs(page)
    claims = page_claims(page)

    assert bullets == len(pairs), (
        f"{page.name} opens {bullets} bullets and the parse anchored {len(pairs)} of them. The "
        f"bold lead is how a claim is named here, so a bullet nobody anchored is a promise no "
        f"guard below can reach: either the bullet does not open with `**bold**` or the anchoring "
        f"regex stopped matching the shape the page uses."
    )

    seen: dict[str, list[str]] = {}
    for anchor, section in pairs:
        seen.setdefault(anchor, []).append(section)
    repeated = {
        anchor: sections for anchor, sections in seen.items() if len(sections) > 1
    }

    assert len(pairs) == len(claims), (
        f"{page.name} publishes {len(pairs)} claims under {len(claims)} distinct anchors: "
        f"{repeated}. Two bullets open with the same bold text, so they are one single claim to "
        f"everything downstream and only one of them is ever exercised. Reword one of the two —the "
        f"bold lead is the name of the claim, and two claims cannot share a name."
    )


def test_the_two_languages_publish_the_same_limits() -> None:
    """The Spanish page carries the same claims, section by section, so neither can grow alone.

    Only the English one is anchored to the checks above, so a limit added ONLY to `.es.md` would be
    published to half the readers with nothing running it. This is a COUNT and not a judgement about
    what the translations SAY: an equality is mechanical, a language is not — the same line
    `test_docs_are_bilingual` draws, held here per section so the failure names where to look.

    The sections are lined up by ORDER and not by name, because their names are the one part that is
    genuinely translated. Their order is not: the two pages are the same document twice.
    """
    english = _claims_per_section(_PAGE)
    spanish = _claims_per_section(_SPANISH_PAGE)

    assert len(english) == len(spanish), (
        f"the pages do not have the same sections: {[name for name, _ in english]} vs "
        f"{[name for name, _ in spanish]}"
    )
    drifted = [
        (left, right)
        for left, right in zip(english, spanish, strict=True)
        if left[1] != right[1]
    ]
    assert drifted == [], (
        f"these sections publish a different number of limits in each language: {drifted}. "
        f"One of the two grew a claim the other does not make."
    )


@pytest.mark.parametrize("claim", sorted(page_claims()), ids=lambda claim: claim[:60])
def test_every_claim_of_the_page_is_accounted_for(claim: str) -> None:
    """Each bullet is either exercised here or DECLARED as not executable, with its reason.

    One test per claim rather than one list: the failure names the sentence you have to deal with
    instead of handing back a wall of them.
    """
    assert claim in _covered() or claim in _NOT_EXECUTABLE, (
        f"{_PAGE.name} publishes a limit nothing here runs: {claim!r}. Add a check to `_CHECKS` "
        f"(or to `_SESSION_CHECKS` if it needs rows), or declare it in `_NOT_EXECUTABLE` with the "
        f"reason it cannot be run. A limit nobody exercises is a limit that stops being true "
        f"without anybody noticing."
    )


def test_no_entry_of_the_tables_is_a_ghost() -> None:
    """The other direction: nothing here checks a promise the page no longer makes.

    A claim that gets reworded or deleted would otherwise leave its check behind, still green,
    still certifying a sentence no reader can find.
    """
    claims = set(page_claims())
    ghosts = sorted((_covered() | set(_NOT_EXECUTABLE)) - claims)

    assert ghosts == [], (
        f"these are checked or declared here and are no longer bullets of {_PAGE.name}: {ghosts}. "
        f"Either the page reworded the claim —in which case retype the anchor— or it dropped it, "
        f"in which case the check goes with it."
    )


def test_nothing_is_both_exercised_and_declared_unrunnable() -> None:
    """A claim cannot be in both tables: one of the two entries would always be a lie."""
    both = sorted(_covered() & set(_NOT_EXECUTABLE))

    assert both == [], f"exercised AND declared not executable: {both}"


# --------------------------------------------------------------------------------------------
# And the claims themselves.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("claim", sorted(_CHECKS), ids=lambda claim: claim[:60])
def test_the_claim_still_holds(claim: str) -> None:
    """The limit the page publishes is the limit the ORM has. One test per sentence."""
    _CHECKS[claim]()


@pytest.mark.parametrize("claim", sorted(_SESSION_CHECKS), ids=lambda claim: claim[:60])
def test_the_claim_still_holds_over_rows(
    claim: str, sqlite_session: SnakeSession
) -> None:
    """The same, for the claims that need rows written and read back."""
    _SESSION_CHECKS[claim](sqlite_session)
