"""The compiler guards for TYPE-SPECIFIC parameters.

Every type knob belongs to ONE family: `int_size` to `int`, `max_length` to `str`, `json_storage`
to `dict`, `precision`/`scale` to `Decimal`. Putting one on another family is an ILLEGAL STATE.

The specifiers (`snake_int`, `snake_str`, `snake_json`, `snake_decimal`) make the CHECKER offer
only the knob of their own family, but they never get to prevent the mistake: they return `Any`
—`@dataclass_transform` demands it— so `SnakeColumn[str] = snake_int(size=...)` still looks fine to
it. Typing them as `SnakeColumn[str]` is no good either: the descriptor is INVARIANT in `T` (its
`__set__` forces that), and then no `| None` column would compile at all.

That is why the compiler guard is the one that closes the door: it fails ON IMPORT, in our own
language. These tests use exactly the gap that is left —the right specifier over the wrong
annotation— because that is the mistake a user can actually make today.

Without them the whole family had no net, and it showed: `precision`/`scale` had no guard and slid
all the way down to the DDL emitting `TEXT(12,2)`, which does not blow up on import but during the
`migrate`, as a raw Postgres syntax error.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from snakeorm.compiler import compile_model
from snakeorm.core.exceptions import SnakeModelDefinitionError
from snakeorm.fields import (
    SnakeColumn,
    snake_auto,
    snake_column,
    snake_datetimetz,
    snake_decimal,
    snake_int,
    snake_json,
    snake_str,
)
from snakeorm.metadata import SnakeDecimalParams, SnakeIntSize, SnakeJsonStorage


def test_int_size_on_non_int_raises() -> None:
    """`int_size` on a column that is not an `int` fails AT COMPILE TIME."""

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        name: SnakeColumn[str] = snake_int(size=SnakeIntSize.SMALLINT)

    with pytest.raises(SnakeModelDefinitionError, match="snake_int"):
        compile_model(Bad)


def test_max_length_on_non_str_raises() -> None:
    """`max_length` on a column that is not a `str` fails AT COMPILE TIME."""

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        age: SnakeColumn[int] = snake_str(max_length=50)

    with pytest.raises(SnakeModelDefinitionError, match="snake_str"):
        compile_model(Bad)


def test_json_storage_on_non_dict_raises() -> None:
    """`json_storage` on a column that is not a `dict` fails AT COMPILE TIME."""

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        created: SnakeColumn[str] = snake_json(storage=SnakeJsonStorage.JSON)

    with pytest.raises(SnakeModelDefinitionError, match="snake_json"):
        compile_model(Bad)


def test_precision_on_non_decimal_raises() -> None:
    """`precision` on a column that is not a `Decimal` fails AT COMPILE TIME.

    This is the gap that left the family uncovered: today `precision` goes through no guard at all
    and `migration/ddl.py` concatenates it onto the type WITHOUT looking, emitting `TEXT(12,2)`.
    The failure lands during the `migrate` and in the engine's language, not here and in ours.
    """

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        name: SnakeColumn[str] = snake_decimal(precision=12, scale=2)

    with pytest.raises(SnakeModelDefinitionError, match="snake_decimal"):
        compile_model(Bad)


def test_scale_cannot_exist_without_its_precision() -> None:
    """A LOOSE `scale` can no longer even be constructed.

    It used to be a writable state you had to catch with a guard: `scale` was one more flat field
    of `SnakeColumnInfo` and could travel alone, or on a text column. Now it only exists INSIDE
    `SnakeDecimalParams`, which demands its `precision`. The illegal state stopped being an error
    that gets detected and became a sentence that cannot be pronounced, which is where this
    project is headed.
    """
    with pytest.raises(TypeError):
        SnakeDecimalParams(scale=2)  # type: ignore[call-arg]  # `precision` is missing, and it is mandatory


def test_each_knob_is_accepted_on_its_own_family() -> None:
    """The four knobs ARE accepted on the family they belong to.

    The guard has to reject the illegal state without getting in the way of the legal one: if this
    ever failed, the guard would be shut too tight and worse than not having it.
    """

    class Good:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        age: SnakeColumn[int] = snake_int(size=SnakeIntSize.SMALLINT)
        name: SnakeColumn[str] = snake_str(max_length=50)
        meta: SnakeColumn[dict] = snake_json(storage=SnakeJsonStorage.JSON)
        price: SnakeColumn[Decimal] = snake_decimal(precision=12, scale=2)

    table = compile_model(Good)
    assert table.get_column("age") is not None
    assert table.get_column("name") is not None
    assert table.get_column("meta") is not None
    assert table.get_column("price") is not None


def test_a_parameterised_dict_is_still_a_dict_column() -> None:
    """`SnakeColumn[dict[str, object]]` compiles. It used to blow up at import.

    And the message contradicted itself: "its type is 'dict' ... either change it to dict", asking
    the user to convert X into X. Two causes — `dict[str, object] is dict` is `False`, and
    `dict[str, object].__name__` has been `'dict'` since 3.10, so the complaint printed the same
    name on both sides and erased the only useful clue.

    This matters beyond the message. The annotation the guide recommends is a bare
    `SnakeColumn[dict]`, which is `dict[Any, Any]`: `doc.payload["k"]` comes back `Any` and
    `.method_that_does_not_exist()` compiles green. The project's rule number one is zero `Any`, and
    the ORM was FORCING it — writing the correct thing raised. `mypy --strict` even flags the
    recommended form with `[type-arg]`, so the guide's advice fails the project's own strict gate.
    """

    class Doc:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        payload: SnakeColumn[dict[str, object]] = snake_json(
            storage=SnakeJsonStorage.JSON
        )

    table = compile_model(Doc)

    assert table.get_column("payload") is not None


def test_a_parameterised_list_is_still_a_list_column() -> None:
    """The same for `list[str]`, which is the other family a user parameterises in practice."""

    class Tags:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        names: SnakeColumn[list[str]] = snake_column()

    assert compile_model(Tags).get_column("names") is not None


def test_a_bool_is_still_refused_where_an_int_family_is_declared() -> None:
    """The floor, and it is the reason `accepts` compared by identity in the first place.

    `bool` is a subclass of `int`, and accepting it would size a boolean column as an integer.
    Unwrapping the ORIGIN does not open that door — `get_origin(bool)` is `None`, so `bool` still
    compares as itself — but a fix written with `issubclass` would have opened it, and nothing else
    here would have noticed.
    """

    class Flag:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        ok: SnakeColumn[bool] = snake_int(size=SnakeIntSize.SMALLINT)

    with pytest.raises(SnakeModelDefinitionError, match="snake_int"):
        compile_model(Flag)


def test_the_guard_names_the_specifier_the_user_actually_wrote() -> None:
    """`snake_auto()` must not be reported as `snake_int()`. The user never wrote that.

    The message took the declarator from the FAMILY, so it named a call that does not appear in the
    file being complained about — and it did it in the best-designed guard of the compiler, whose
    whole point is to say WHAT to write instead of just what is wrong.
    """

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        flag: SnakeColumn[str] = snake_auto()

    with pytest.raises(SnakeModelDefinitionError) as caught:
        compile_model(Bad)

    message = str(caught.value)
    assert "snake_auto()" in message
    assert "snake_int()" not in message, "it named a call the user did not make"


def test_the_guard_tells_the_two_date_declarators_apart() -> None:
    """`snake_datetimetz()` reported as `snake_datetime()` is the same defect in the other family."""

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        when: SnakeColumn[str] = snake_datetimetz()

    with pytest.raises(SnakeModelDefinitionError) as caught:
        compile_model(Bad)

    assert "snake_datetimetz()" in str(caught.value)


def test_the_guard_does_not_report_a_parameter_the_user_left_alone() -> None:
    """`snake_auto()` takes no size, so "declares size=BIGINT" is a second false fact in one line.

    `declared` listed every field that was not `None`, which includes the ones sitting at their
    DEFAULT. The reader is then hunting for a `size=` they never typed.
    """

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        flag: SnakeColumn[str] = snake_auto()

    with pytest.raises(SnakeModelDefinitionError) as caught:
        compile_model(Bad)

    assert "size=" not in str(caught.value), (
        "it reported a parameter the user did not set"
    )


def test_a_parameter_the_user_did_set_is_still_reported() -> None:
    """The floor: filtering the defaults out must not silence what WAS written.

    "declares nothing with snake_int()" would be a worse message than the wrong one.
    """

    class Bad:
        id: SnakeColumn[int] = snake_column(primary_key=True)
        name: SnakeColumn[str] = snake_int(size=SnakeIntSize.SMALLINT)

    with pytest.raises(SnakeModelDefinitionError, match="SMALLINT"):
        compile_model(Bad)
