"""The demos' migrations SAY the same thing as the models. Nobody was watching that.

The demos are this project's framework integration tests, and their schema has two sources: the
models in `shared/models/` and the files in `apps/*/migrations/`. Nothing checked that they matched,
and they had already stopped matching: twenty-one migrations declared
`python_type=datetime.datetime` —that is, `TIMESTAMP`, wall-clock time— while the models said
`SnakeUtc` —`TIMESTAMPTZ`, an instant— ever since the two date declarators were split. Twelve out of
twenty tables differed.

And it was BLIND twice over, which is what made it last: the demos' suites build the schema **from
the models**, so they never run these migrations; and they do it on **SQLite**, where the two date
types are the same TEXT and the difference is invisible even when running them.

The check is the one `makemigrations` already uses: replay the history and ask the autodetector what
it would take to get to the models. If ANYTHING is needed, there is drift — and the message says
what, which is exactly what one needs to fix it.
"""

from __future__ import annotations

import pathlib

import pytest
from snakeorm.migration import autodetect, load

from shared.models import MODELS, VIEWS

# The three demos have the SAME domain and the SAME history per domain: that is the premise of
# `frameworks/`, and checking all three is what stops one of them falling behind unnoticed.
_DEMOS = ("django", "fastapi", "flask")
_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _directories(demo: str) -> list[pathlib.Path]:
    """A demo's `apps/*/migrations`, in a stable order."""
    return sorted((_ROOT / demo / "apps").glob("*/migrations"))


def _table_of(model: object) -> object:
    """A model's compiled table, exactly as the autodetector sees it."""
    from snakeorm import snake_table

    return snake_table(model)  # type: ignore[arg-type]


@pytest.mark.parametrize("demo", _DEMOS)
def test_the_demo_has_migrations_at_all(demo: str) -> None:
    """That migrations were found at all. Without this, the drift test would go green looking at nothing.

    It is the trap of any test that discovers files: if the glob stops matching, "no differences"
    holds vacuously and the guard turns into decoration.
    """
    directories = _directories(demo)

    assert directories, f"no migration was found in {demo}/apps/*/migrations"
    assert sum(len(load(str(d))) for d in directories) >= 5


@pytest.mark.parametrize("demo", _DEMOS)
def test_the_migrations_describe_the_same_schema_as_the_models(demo: str) -> None:
    """Replaying the history and reaching the models must not require a single extra operation.

    It is exactly what `makemigrations` does: if it had anything to generate, then the migration file
    and the model say different things. The demo would deploy a schema that contradicts its own
    source of truth.
    """
    migrations = [mig for d in _directories(demo) for mig in load(str(d))]
    # The VIEWS go in too. They are not tables and are kept out of `MODELS` for the DDL's sake —
    # created last, dropped first — but they ARE part of the schema, and a comparison that left them
    # out would read a view present in the history as one the models want dropped. It said exactly
    # that the first time: one spare `DropView`.
    current = [_table_of(model) for model in (*MODELS, *VIEWS)]

    outstanding = autodetect(migrations, current)  # type: ignore[arg-type]

    assert outstanding == [], (
        f"the migrations of {demo} and the models do NOT say the same thing. The autodetector is "
        f"missing {len(outstanding)} operation(s) to get from the history to the models: "
        f"{[type(op).__name__ for op in outstanding]}. Regenerate with `makemigrations --only` "
        f"against a module that exposes ONLY that domain — not `shared.models`, whose `__init__` "
        f"injects the whole graph into every domain module, so `--only` would emit all 29 tables. "
        f"And a VIEW never comes out of it: `--only` collects by `__snake_registry__`, which a "
        f"SnakeView does not carry, so its CreateView is written by hand. `squash` is NO use "
        f"either: it replays over the history and never opens the models."
    )
