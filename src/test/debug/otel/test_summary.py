"""`db.query.summary`: the short shape of a statement, which is what NAMES the span.

The convention is explicit that the span name is the summary (`SELECT orders`) and NOT the query
text: Jaeger gives `db.query.text` no special formatting, so a span named after the whole SQL is an
unreadable row in the timeline. The summary is `<operation> <collection>`, and the operation alone
when there is no single table to name.
"""

from __future__ import annotations

import pytest

from snakeorm.debug.otel import summarise


@pytest.mark.parametrize(
    ("sql", "operation", "collection"),
    [
        ('SELECT "id" FROM "orders" AS e1 WHERE e1."id" = $1', "SELECT", "orders"),
        ('INSERT INTO "orders" ("id") VALUES ($1)', "INSERT", "orders"),
        ('UPDATE "orders" SET "total" = $1 WHERE "id" = $2', "UPDATE", "orders"),
        ('DELETE FROM "orders" WHERE "id" = $1', "DELETE", "orders"),
        ('CREATE TABLE "orders" ("id" INTEGER)', "CREATE", "orders"),
        ('DROP TABLE IF EXISTS "orders"', "DROP", "orders"),
        ("SELECT `id` FROM `orders` WHERE `id` = %s", "SELECT", "orders"),
        ("select id from orders where id = ?", "SELECT", "orders"),
        # SCHEMA-QUALIFIED, which is what SnakeORM actually emits against Postgres. Caught in
        # Jaeger, not here: every span of a real request read `SELECT public`, because the first
        # identifier after FROM is the SCHEMA and the collection is the second.
        (
            'SELECT "id" FROM "public"."users" WHERE "id" = %s',
            "SELECT",
            "users",
        ),
        ('INSERT INTO "public"."orders" ("id") VALUES (%s)', "INSERT", "orders"),
        ("UPDATE `shop`.`orders` SET `total` = %s", "UPDATE", "orders"),
    ],
)
def test_operation_and_collection_come_out_of_the_sql(
    sql: str, operation: str, collection: str
) -> None:
    """The verb and the table are pulled from the emitted SQL, quoted the way any of the three engines quotes."""
    summary = summarise(sql)

    assert (summary.operation, summary.collection) == (operation, collection)


def test_the_summary_text_joins_the_two() -> None:
    """`db.query.summary` is `<operation> <collection>`, which is also the span's name."""
    assert summarise('SELECT * FROM "orders"').text == "SELECT orders"


def test_a_statement_with_no_table_keeps_only_its_verb() -> None:
    """`COMMIT` names no collection: the summary is the verb alone, never `COMMIT ` with a hole."""
    summary = summarise("COMMIT")

    assert (summary.collection, summary.text) == ("", "COMMIT")


def test_empty_sql_summarises_to_nothing_instead_of_blowing_up() -> None:
    """An empty statement gives an empty summary: a report is not worth losing over a stray record."""
    summary = summarise("   ")

    assert (summary.operation, summary.collection, summary.text) == ("", "", "")


def test_the_verb_is_uppercased_and_the_table_is_not() -> None:
    """The operation is normalised to upper case (the convention's form); the identifier is left alone."""
    summary = summarise('select * from "Orders"')

    assert (summary.operation, summary.collection) == ("SELECT", "Orders")


def test_a_join_names_the_table_the_query_reads_from() -> None:
    """With a JOIN the collection is the FROM table, not the joined one: one span, one primary table."""
    sql = 'SELECT * FROM "orders" AS e1 JOIN "customers" AS e2 ON e2."id" = e1."customer_id"'

    assert summarise(sql).collection == "orders"


def test_a_qualified_name_splits_into_namespace_and_collection() -> None:
    """`"public"."users"` is a SCHEMA and a table: the schema goes to `db.namespace`, not to the name.

    This is the bug the live demo showed and no unit test did: SnakeORM emits every Postgres table
    schema-qualified, so the whole trace read `SELECT public` and grouping by `db.collection.name`
    put sixty-eight different tables in one bucket.
    """
    summary = summarise('SELECT * FROM "public"."users"')

    assert (summary.namespace, summary.collection, summary.text) == (
        "public",
        "users",
        "SELECT users",
    )


def test_an_unqualified_name_has_no_namespace() -> None:
    """Without a schema there is no namespace: the attribute is omitted rather than left empty."""
    assert summarise('SELECT * FROM "orders"').namespace == ""
