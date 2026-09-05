"""A real DB VIEW, mapped as a READ-ONLY model, queried and NAVIGATED end to end.

Against a real Postgres (its own schema with UNIQUE names `iv_*`): it creates real tables, seeds,
creates a VIEW with `CREATE VIEW` and maps it with `@snake_view`. It checks end to end: (a) querying
the view returns TYPED rows; (b) navigating from a model to the view with `include` (to-many
select-in); (c) navigating from the view to a model with `include` (to-one LEFT JOIN); (d) writing to
the view (`session.add`) fails. The view's FK is NOT guaranteed by the DB: the navigation is pure
SQL generation (which is why the view's DDL carries no constraints).
"""

from __future__ import annotations

from typing import Any, cast

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from snakeorm.decorators import snake_model, snake_view
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.drivers.psycopg import PsycopgDriver
from snakeorm.core.exceptions import SnakeUnsupportedFeature
from snakeorm.fields import (
    SnakeColumn,
    SnakeToMany,
    SnakeToOne,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.linker.linker import snake_link
from snakeorm.model import SnakeModel, SnakeView
from snakeorm.query import SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


@snake_model(table="iv_users")
class IvUser(SnakeModel):
    """User. Its to-many `classes` points at a VIEW (not at a table)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    classes: SnakeToMany[IvUserClasses] = snake_to_many("user")


@snake_model(table="iv_classes")
class IvClass(SnakeModel):
    """Class (subject)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    name: SnakeColumn[str] = snake_str()


@snake_model(table="iv_enrollments")
class IvEnrollment(SnakeModel):
    """Enrollment: joins a user with a class (the view flattens this join)."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    user_id: SnakeColumn[int] = snake_int()
    class_id: SnakeColumn[int] = snake_int()


@snake_view(
    sql=(
        "SELECT e.user_id AS user_id, c.name AS class_name "
        "FROM iv_enrollments e JOIN iv_classes c ON e.class_id = c.id"
    ),
    name="iv_user_classes",
)
class IvUserClasses(SnakeView):
    """Read-only VIEW: (user_id, class_name), navigable in both directions."""

    user_id: SnakeColumn[int] = snake_int()
    class_name: SnakeColumn[str] = snake_str()
    user: SnakeToOne[IvUser] = snake_to_one(user_id)


_DDL = (
    "DROP VIEW IF EXISTS iv_user_classes",
    "DROP TABLE IF EXISTS iv_enrollments, iv_classes, iv_users CASCADE",
    "CREATE TABLE iv_users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE iv_classes (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
    "CREATE TABLE iv_enrollments ("
    " id INTEGER PRIMARY KEY,"
    " user_id INTEGER NOT NULL REFERENCES iv_users(id),"
    " class_id INTEGER NOT NULL REFERENCES iv_classes(id))",
    # The real VIEW: it flattens the enrollment↔class join. It carries no constraints (it is a view).
    "CREATE VIEW iv_user_classes AS"
    " SELECT e.user_id AS user_id, c.name AS class_name"
    " FROM iv_enrollments e JOIN iv_classes c ON e.class_id = c.id",
)

_SEED = (
    "INSERT INTO iv_users VALUES (1, 'Ada'), (2, 'Linus')",
    "INSERT INTO iv_classes VALUES (10, 'Álgebra'), (20, 'Física'), (30, 'Química')",
    # Ada: Álgebra and Física; Linus: Química.
    "INSERT INTO iv_enrollments VALUES (1, 1, 10), (2, 1, 20), (3, 2, 30)",
)


@pytest.fixture(scope="module")
def session() -> SnakeSession:
    """Creates the schema + the view, seeds and returns a session against the real Postgres."""
    try:
        connection = psycopg2.connect(dsn())
    except psycopg2.OperationalError:  # pragma: no cover - with no DB there is no test
        pytest.skip(NO_SERVER_REASON)
    snake_link()
    driver = PsycopgDriver(connection)
    for statement in (*_DDL, *_SEED):
        driver.execute(statement, ())
    driver.commit()
    return SnakeSession(driver, PostgresDialect())


def test_query_a_view_returns_typed_rows(session: SnakeSession) -> None:
    """(a) `session.all(SnakeQuery(view))` returns typed rows from the real view."""
    rows = session.all(SnakeQuery(IvUserClasses))
    assert sorted((r.user_id, r.class_name) for r in rows) == [
        (1, "Física"),
        (1, "Álgebra"),
        (2, "Química"),
    ]


def test_navigate_from_model_to_view_with_include(session: SnakeSession) -> None:
    """(b) `include(IvUser.classes)` loads the view as a to-many: user.classes[0].class_name is typed."""
    users = session.all(
        SnakeQuery(IvUser).include(IvUser.classes).order_by(IvUser.id.asc())
    )
    by_user = {
        user.name: sorted(cls.class_name for cls in user.classes) for user in users
    }
    assert by_user == {"Ada": ["Física", "Álgebra"], "Linus": ["Química"]}


def test_navigate_from_view_to_model_with_include(session: SnakeSession) -> None:
    """(c) `include(IvUserClasses.user)` loads the model from the view: view_row.user.name is typed."""
    rows = session.all(
        SnakeQuery(IvUserClasses)
        .include(IvUserClasses.user)
        .filter(IvUserClasses.class_name == "Química")
    )
    assert len(rows) == 1
    assert rows[0].user.name == "Linus"


def test_add_of_a_view_row_is_rejected(session: SnakeSession) -> None:
    """(d) `session.add(view_row)` fails: a view is read-only (runtime guard)."""
    instance = cast("Any", IvUserClasses(user_id=1, class_name="Álgebra"))
    with pytest.raises(SnakeUnsupportedFeature, match="is a READ-ONLY view"):
        session.add(instance)
