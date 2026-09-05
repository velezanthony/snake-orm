"""`json_get()` EXECUTED on the three engines, which had never happened.

The feature was held up by emission tests alone, and JSON is the worst place for that: the three do
not merely spell it differently, they use three different MECHANISMS —`->>` with a `::cast` on
Postgres, `JSON_UNQUOTE(JSON_EXTRACT(...))` with a `CAST(... AS SIGNED)` on MySQL, `json_extract`
with `CAST(... AS INTEGER)` on SQLite— and a string that looks right proves nothing about any of
them.

The declared `as_type` is the whole point of the API and the reason a comparison is asserted here
and not only a read: without the cast, `meta.json_get("size") > 100` compares TEXT, where `'9'` is
greater than `'100'` and nobody notices.

SQLite stores JSON as TEXT and MySQL declares `Cap.JSON` degraded, but both READ it back exactly —
what they lose is indexing and validation, not the value. So this is a case where the three agree
on the answer and had simply never been asked.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    snake_int,
    snake_json,
    snake_model,
)
from test.scenarios.engines import three_sessions

pytestmark = pytest.mark.integration

_ENGINES = ["postgres", "mysql", "sqlite"]


@snake_model(table="jsn_docs")
class Doc(SnakeModel):
    """A document with a nested path, so a multi-key walk has somewhere to go."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    meta: SnakeColumn[dict] = snake_json()


_DOCS = [
    (1, {"size": 9, "name": "small", "owner": {"name": "ada"}}),
    (2, {"size": 100, "name": "big", "owner": {"name": "grace"}}),
]


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, SnakeSession]]:
    """The three engines with the same two documents."""
    with three_sessions([Doc]) as sessions:
        for session in sessions.values():
            session.add_all([Doc(id=i, meta=m) for i, m in _DOCS])
            session.commit()
        yield sessions


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_key_comes_back_as_the_declared_type(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Reading one key, cast to what was declared. Three mechanisms, one answer."""
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Doc).order_by(Doc.id.asc()),
        Doc.id,
        Doc.meta.json_get("name", as_type=str),
    )

    assert [(row_id, str(name)) for row_id, name in rows] == [(1, "small"), (2, "big")]


@pytest.mark.parametrize("engine", _ENGINES)
def test_a_nested_path_walks_in_one_access(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """Several keys walk a nested document in ONE access, and each engine spells the path its way."""
    session = engines[engine]

    rows = session.select(
        SnakeQuery(Doc).order_by(Doc.id.asc()),
        Doc.meta.json_get("owner", "name", as_type=str),
    )

    assert [str(row[0]) for row in rows] == ["ada", "grace"]


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_cast_is_what_makes_a_comparison_numeric(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """THE assertion emission cannot make, and the reason `as_type` exists.

    `9` and `100` are chosen so the two orders disagree: numerically `9 < 100`, as TEXT `'9' > '100'`.
    A dialect that dropped the cast would return document 1 here and look perfectly healthy.
    """
    session = engines[engine]

    found = session.all(
        SnakeQuery(Doc).filter(Doc.meta.json_get("size", as_type=int) > 50)
    )

    assert [doc.id for doc in found] == [2], (
        "the JSON value was compared as TEXT: '9' sorts above '100'"
    )


@pytest.mark.parametrize("engine", _ENGINES)
def test_the_whole_document_survives_the_round_trip(
    engine: str, engines: dict[str, SnakeSession]
) -> None:
    """The value goes in and comes out exact, degraded storage or not.

    MySQL declares `Cap.JSON` degraded and SQLite stores it as TEXT: what they lose is indexing and
    validation, never fidelity. That distinction is doctrine here, so it is asserted rather than
    trusted.
    """
    session = engines[engine]

    first = session.first(SnakeQuery(Doc).filter(Doc.id == 1))

    assert first is not None
    assert first.meta == {"size": 9, "name": "small", "owner": {"name": "ada"}}
