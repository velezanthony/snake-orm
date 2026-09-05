"""The attribute names we write are the ones the CURRENT convention defines, checked against it.

The exporter cannot import `opentelemetry.semconv`: the channel has to work with the API alone —and
with nothing installed at all—, so the names live in our module as literals. A literal is exactly
what goes stale: `db.system` → `db.system.name`, `db.statement` → `db.query.text` and
`db.operation` → `db.operation.name` are all deprecations that already happened, and a span carrying
the old names is a span the backend groups under a column nobody looks at any more.

So the equality gets CHECKED rather than trusted. This is the only kind of net worth writing here:
an equality against the installed package, not a judgement about content. It skips when the
package is absent, because then there is nothing to compare against — and it says so instead of
passing vacuously.
"""

from __future__ import annotations

import pytest

from snakeorm.debug import otel

pytest.importorskip(
    "opentelemetry.semconv._incubating.attributes.db_attributes",
    reason="opentelemetry-semantic-conventions is not installed: nothing to compare against",
)

from opentelemetry.semconv._incubating.attributes import (  # noqa: E402
    code_attributes,
    db_attributes,
)


def test_the_database_attributes_match_the_convention() -> None:
    """Our `db.*` literals are byte for byte what the installed semantic conventions define."""
    assert otel.DB_SYSTEM_NAME == db_attributes.DB_SYSTEM_NAME
    assert otel.DB_QUERY_TEXT == db_attributes.DB_QUERY_TEXT
    assert otel.DB_QUERY_SUMMARY == db_attributes.DB_QUERY_SUMMARY
    assert otel.DB_COLLECTION_NAME == db_attributes.DB_COLLECTION_NAME
    assert otel.DB_NAMESPACE == db_attributes.DB_NAMESPACE
    assert otel.DB_OPERATION_NAME == db_attributes.DB_OPERATION_NAME
    assert otel.DB_RESPONSE_RETURNED_ROWS == db_attributes.DB_RESPONSE_RETURNED_ROWS


def test_the_parameter_prefix_matches_the_convention() -> None:
    """`db.query.parameter.<key>` is the opt-in template; the prefix has to be the real one."""
    template = db_attributes.DB_QUERY_PARAMETER_TEMPLATE

    assert otel.DB_QUERY_PARAMETER_PREFIX == f"{template}."


def test_the_code_attributes_match_the_convention() -> None:
    """The origin maps to the CURRENT `code.*` names, not the `code.filepath`/`code.lineno` pair."""
    assert otel.CODE_FILE_PATH == code_attributes.CODE_FILE_PATH
    assert otel.CODE_LINE_NUMBER == code_attributes.CODE_LINE_NUMBER
    assert otel.CODE_FUNCTION_NAME == code_attributes.CODE_FUNCTION_NAME


def test_the_deprecated_names_are_nowhere_in_the_exporter() -> None:
    """The superseded names never appear: a span carrying both would be indexed twice and read once."""
    written = {value for _name, value in vars(otel).items() if isinstance(value, str)}

    assert db_attributes.DB_SYSTEM not in written
    assert db_attributes.DB_STATEMENT not in written
    assert db_attributes.DB_OPERATION not in written
    assert code_attributes.CODE_FILEPATH not in written
    assert code_attributes.CODE_LINENO not in written


def test_the_engine_names_are_the_conventions_own_values() -> None:
    """`postgresql`, `mysql` and `sqlite` are values of the convention's own enum, not our spelling.

    `mariadb` is a value in its own right there, NOT an alias of `mysql`. SnakeORM reaches both
    through PyMySQL and cannot tell them apart without asking the server, so it reports `mysql` and
    lets whoever knows better declare it.
    """
    values = {member.value for member in db_attributes.DbSystemNameValues}

    assert {"postgresql", "mysql", "sqlite", "mariadb"} <= values
