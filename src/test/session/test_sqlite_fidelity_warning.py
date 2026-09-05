"""Capability warnings when a session opens: ONE per thing the engine does not do, and only once.

The dangerous scenario is "dev on SQLite, prod on Postgres": the nuance does not show up until
production. A warning when the session opens puts it in front of your eyes, and whoever has it under
control silences it with `warnings.filterwarnings("ignore", category=SnakeWarning)`.

It used to be ONE warning with everything concatenated. Now it is one PER CAPABILITY, and the
difference is not cosmetic: concatenated, silencing the one that annoys you silenced the other six
too, and the dedup went by the whole text —so changing a comma in one reason warned about everything
all over again.

Two families, and they are treated differently on purpose:

- The **structural** ones (upsert, FOR UPDATE, ALTER COLUMN...) always warn. Whether the dev is going
  to call `upsert()` cannot be known by reading the models.
- The **type fidelity** ones warn only if some registered model USES that type. Telling somebody who
  has no `Decimal` what happens to a `Decimal` is noise, and noise is what makes people silence the
  whole category and miss the ones that did matter.
"""

from __future__ import annotations

import warnings
from decimal import Decimal

import pytest

import snakeorm.session.shared as session_mod
from snakeorm import (
    PostgresDialect,
    SnakeColumn,
    SnakeSession,
    SnakeWarning,
    SQLiteDialect,
    SQLiteDriver,
    snake_auto,
    snake_decimal,
)
from snakeorm.compiler import compile_model
from snakeorm.registry import SnakeRegistry


@pytest.fixture(autouse=True)
def _reset_dedup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empties the record of warnings already emitted: the dedup is per PROCESS, so without this an
    earlier test that already opened SQLite would leave this one unable to observe the warning."""
    monkeypatch.setattr(session_mod, "_warned_caveats", set())


def _registry_with(*python_types: object) -> SnakeRegistry:
    """An ISOLATED registry with a model declaring exactly those types, and no others.

    Isolated because the fidelity warning looks at which types the registered models use, and the
    global registry of the suite has a bit of everything: on top of it, the difference between
    warning and staying quiet could not be observed.
    """
    registry = SnakeRegistry()
    annotations: dict[str, object] = {"id": SnakeColumn[int]}
    attributes: dict[str, object] = {"id": snake_auto()}
    for index, python_type in enumerate(python_types):
        annotations[f"c{index}"] = SnakeColumn[python_type]  # type: ignore[valid-type]
        attributes[f"c{index}"] = (
            snake_decimal(precision=10, scale=2) if python_type is Decimal else None
        )
    model = type("M", (), {"__annotations__": annotations, **attributes})
    registry.register(model, compile_model(model))
    return registry


def _snake_warnings(captured: list[warnings.WarningMessage]) -> list[str]:
    """The messages of the ORM's own warnings, discarding third-party ones."""
    return [str(w.message) for w in captured if issubclass(w.category, SnakeWarning)]


def test_a_sqlite_session_warns_once_per_capability_not_once_in_a_lump() -> None:
    """Verifies that ONE warning is emitted per capability, each one with its own reason.

    It is the contract the user asked for: once for every thing their database will not let them do.
    With a single concatenated warning you cannot silence one without silencing them all.
    """
    driver = SQLiteDriver.connect(":memory:")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        SnakeSession(driver, SQLiteDialect())

    messages = _snake_warnings(captured)
    assert len(messages) > 1, (
        "the concatenated warning is no good any more: one per capability"
    )
    assert any("FOR UPDATE" in m for m in messages)
    assert any("ALTER TABLE" in m or "columna existente" in m for m in messages)
    assert all("SQLite" in m for m in messages), (
        "each warning names the engine on its own"
    )
    driver.close()


def test_each_capability_warns_only_once_across_sessions() -> None:
    """Verifies the heart of the feature: opening TWO sessions does not repeat a single warning.

    The dedup goes by (engine, capability) and not by the text of the message. With the textual key,
    touching up one reason made EVERYTHING warn again, because the whole string was another one.
    """
    driver = SQLiteDriver.connect(":memory:")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        SnakeSession(driver, SQLiteDialect())
        first = len(_snake_warnings(captured))
        SnakeSession(driver, SQLiteDialect())

    assert len(_snake_warnings(captured)) == first
    driver.close()


def test_a_type_caveat_is_silent_when_no_model_uses_that_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies that what happens to a `Decimal` is not told if there is no `Decimal` at all.

    It is what separates a useful warning from a wall of text everybody silences. The STRUCTURAL
    capabilities do keep warning: whether you will call `upsert()` cannot be read off the models.
    """
    monkeypatch.setattr(session_mod, "registry", _registry_with())
    driver = SQLiteDriver.connect(":memory:")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        SnakeSession(driver, SQLiteDialect())

    messages = _snake_warnings(captured)
    assert not any("Decimal" in m for m in messages)
    assert any("FOR UPDATE" in m for m in messages), (
        "the structural ones do not depend on the model"
    )
    driver.close()


def test_a_type_caveat_fires_when_a_model_does_use_that_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies the other half: the moment a model declares a `Decimal`, the warning shows up.

    Without this test, "never warn at all" would pass the previous test with flying colours.
    """
    monkeypatch.setattr(session_mod, "registry", _registry_with(Decimal))
    driver = SQLiteDriver.connect(":memory:")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        SnakeSession(driver, SQLiteDialect())

    assert any("Decimal" in m for m in _snake_warnings(captured))
    driver.close()


def test_opening_a_postgres_session_does_not_warn() -> None:
    """Verifies that Postgres keeps quiet: it answers `Full()` to the whole catalogue, no caveats.

    A SQLite driver with the Postgres dialect is used on purpose: the warning depends on the
    DIALECT, not on the driver, so the test needs no Postgres server to check the silence.
    """
    driver = SQLiteDriver.connect(":memory:")
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        SnakeSession(driver, PostgresDialect())

    assert _snake_warnings(captured) == []
    driver.close()
