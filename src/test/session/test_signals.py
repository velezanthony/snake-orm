"""Code signals, and the walk over ALL SIX write paths.

That "six" is the point of the file. This branch has caught three bugs of the same shape —a feature
implemented on N-1 sibling surfaces— so here `add` is not tested with the rest assumed: `add`,
`add_all`, `update`, `delete`, `upsert` and the two bulk ones are all walked through.

And the other half: the bulk ones do NOT fire the signals, and that is WARNED about. Neither an
error (it would block a legitimate case) nor silence (that is Django's best known trap). A warning
reminds you while you are looking.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator

import pytest

from snakeorm import SnakeColumn, SnakeModel, SnakeQuery, snake_int, snake_model

from snakeorm.core.signals import SnakeSignal, disconnect_all, signals_of, snake_on


@snake_model(table="sig_orders")
class Order(SnakeModel):
    """Minimal model for observing the signals."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    amount: SnakeColumn[int] = snake_int()


@pytest.fixture(autouse=True)
def sin_handlers() -> Iterator[None]:
    """The handlers live in a global dict: they are cleaned before and after every test."""
    disconnect_all()
    yield
    disconnect_all()


@pytest.fixture
def session_and_record() -> Iterator[tuple[object, list[str]]]:
    """A session against a phoney driver, plus the record of what got executed."""
    from snakeorm import PostgresDialect
    from snakeorm.session import SnakeSession

    executed: list[str] = []

    class DriverFalso:
        """Records the SQL; no engine is needed to observe the signals."""

        def execute(self, sql: str, params: object = ()) -> int:
            executed.append(sql)
            return 1

        def fetch_all(self, sql: str, params: object = ()) -> list[tuple[object, ...]]:
            """Returns as many rows as the INSERT carries groups of VALUES.

            `add_all` with RETURNING matches the returned rows to the instances by position
            (`zip(..., strict=True)`), so a double that always returned one row would break
            through the scaffolding and not through what we want to observe.
            """
            executed.append(sql)
            rows = sql.count("), (") + 1
            return [(i, 100) for i in range(1, rows + 1)]

        def commit(self) -> None: ...
        def rollback(self) -> None: ...

    yield SnakeSession(DriverFalso(), PostgresDialect()), executed  # type: ignore[arg-type]


def _observar() -> list[tuple[str, int]]:
    """Connects the four signals and returns the list where the firings get noted down."""
    vistos: list[tuple[str, int]] = []

    for signal in SnakeSignal:

        @snake_on(Order, signal)
        def apuntar(order: Order, signal: SnakeSignal = signal) -> None:
            """Notes down which signal fired and over which row."""
            vistos.append((signal.value, order.id))

    return vistos


def test_add_fires_pre_and_post_save(
    session_and_record: tuple[object, list[str]],
) -> None:
    """`add`: PRE before writing, POST afterwards."""
    session, _ = session_and_record
    vistos = _observar()

    session.add(Order(id=1, amount=100))  # type: ignore[attr-defined]

    assert vistos == [("pre_save", 1), ("post_save", 1)]


def test_add_all_fires_for_every_instance(
    session_and_record: tuple[object, list[str]],
) -> None:
    """`add_all`: ALL the PREs before emitting anything, and then all the POSTs.

    The order matters: a handler can modify the instance, and firing the PRE halfway through the
    batch would leave some rows with the change and others without it.
    """
    session, _ = session_and_record
    vistos = _observar()

    session.add_all([Order(id=1, amount=10), Order(id=2, amount=20)])  # type: ignore[attr-defined]

    assert [v[0] for v in vistos] == ["pre_save", "pre_save", "post_save", "post_save"]


def test_update_fires_save_signals(
    session_and_record: tuple[object, list[str]],
) -> None:
    """`update` is a save too: it fires PRE/POST_SAVE."""
    session, _ = session_and_record
    vistos = _observar()

    session.update(Order(id=1, amount=100))  # type: ignore[attr-defined]

    assert vistos == [("pre_save", 1), ("post_save", 1)]


def test_upsert_fires_save_signals(
    session_and_record: tuple[object, list[str]],
) -> None:
    """`upsert` is the fourth save path, and it is an easy one to forget."""
    session, _ = session_and_record
    vistos = _observar()

    session.upsert(Order(id=1, amount=100), on_conflict=[Order.id])  # type: ignore[attr-defined]

    assert vistos == [("pre_save", 1), ("post_save", 1)]


def test_delete_fires_the_delete_signals(
    session_and_record: tuple[object, list[str]],
) -> None:
    """`delete`: PRE_DELETE before and POST_DELETE after, not the save ones."""
    session, _ = session_and_record
    vistos = _observar()

    session.delete(Order(id=1, amount=100))  # type: ignore[attr-defined]

    assert vistos == [("pre_delete", 1), ("post_delete", 1)]


@pytest.mark.parametrize("operation", ["update_where", "delete_where"])
def test_the_bulk_writes_warn_instead_of_failing_or_hiding(
    session_and_record: tuple[object, list[str]], operation: str
) -> None:
    """THE design decision: the bulk write WARNS about the signals it is skipping.

    It does not fail —the bulk path is legitimate and sometimes exactly what you want— and it does
    not keep quiet, which is Django's trap. The warning names the concrete signals so that you can
    decide what to do about them.
    """
    session, _ = session_and_record
    _observar()
    query = SnakeQuery(Order).filter(Order.id == 1)

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        if operation == "update_where":
            session.update_where(query, [(Order.amount, 5)])  # type: ignore[attr-defined]
        else:
            session.delete_where(query)  # type: ignore[attr-defined]

    assert len(recorded) == 1
    mensaje = str(recorded[0].message)
    assert operation in mensaje
    assert "post_save" in mensaje and "pre_save" in mensaje
    assert "trigger" in mensaje, (
        "the warning has to say the alternative that DOES always hold"
    )


def test_a_bulk_write_without_handlers_says_nothing(
    session_and_record: tuple[object, list[str]],
) -> None:
    """With no signals connected there is nothing to warn about, and warning anyway would be noise.

    A warning that always comes out is one you learn to ignore, and then it stops warning about the
    case that matters.
    """
    session, _ = session_and_record

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        session.delete_where(SnakeQuery(Order).filter(Order.id == 1))  # type: ignore[attr-defined]

    assert recorded == []


def test_a_failing_handler_aborts_the_write(
    session_and_record: tuple[object, list[str]],
) -> None:
    """If a handler raises, the exception travels up and the write never gets emitted.

    The handlers run INSIDE the transaction on purpose: swallowing the error would turn a broken
    `pre_save` into half-saved data without anybody finding out.
    """
    session, executed = session_and_record

    @snake_on(Order, SnakeSignal.PRE_SAVE)
    def rechazar(order: Order) -> None:
        """Handler that refuses."""
        raise ValueError("invalid amount")

    with pytest.raises(ValueError, match="invalid amount"):
        session.add(Order(id=1, amount=-1))  # type: ignore[attr-defined]

    assert executed == [], "no SQL should have been emitted"


def test_signals_of_lists_only_what_is_connected() -> None:
    """`signals_of` is what the warning reads and what `check` will list: only what is connected."""
    assert signals_of(Order) == ()

    @snake_on(Order, SnakeSignal.POST_DELETE)
    def nada(order: Order) -> None:
        """Test handler."""

    assert signals_of(Order) == (SnakeSignal.POST_DELETE,)
