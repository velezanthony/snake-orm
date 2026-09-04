"""An EXECUTABLE walk through SnakeORM's API against a real Postgres.

Run `uv run python -m examples.tour`. It connects, creates the schema of the publishing domain
(`examples/showcase.py`), seeds it and walks the API in NUMBERED SECTIONS. For every operation it
prints: the title, the SQL emitted (`query.to_sql(dialect)`, or whichever emitter applies) and the
real RESULT Postgres gives back.

It is not just a demo: it is living documentation. The SQL you see is EXACTLY the SQL that runs, and
the guards (section 15) are shown as what they are -a safety feature, not a failure-.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from examples.showcase import (
    BookStats,
    ExAuthor,
    ExBook,
    ExBookAuthor,
    ExCatalogEntry,
    ExCountry,
    ExEdition,
    ExNote,
    ExPrinting,
    ExPublisher,
    ExTag,
    PublisherStats,
    create_schema,
    register_uuid_write_adapter,
    seed,
)
from snakeorm.decorators import snake_table
from snakeorm.dialects import PostgresDialect, SnakeDialect
from snakeorm.drivers import PsycopgDriver
from snakeorm.core.exceptions import (
    SnakeEmitError,
    SnakeRelationshipNotLoaded,
    SnakeUnsupportedFeature,
)
from snakeorm.expressions import count
from snakeorm.fields import SnakePrefetch
from snakeorm.linker.linker import snake_link
from snakeorm.migration import emit_create_table
from snakeorm.query import SnakeJoin, SnakeQuery
from snakeorm.session import SnakeSession
from test.scenarios.db import dsn

_WIDTH = 82


# ─────────────────────────────────────────────────────────────────────────────
# Printing helpers
# ─────────────────────────────────────────────────────────────────────────────
def _section(number: int, title: str) -> None:
    """Prints the header of a numbered section (the marker the integration test looks for)."""
    print()
    print("=" * _WIDTH)
    print(f" SECTION {number}: {title}")
    print("=" * _WIDTH)


def _step(title: str) -> None:
    """Prints the subtitle of one concrete operation inside a section."""
    print(f"\n· {title}")


def _sql(pair: tuple[str, tuple[object, ...]]) -> None:
    """Prints the SQL emitted and its parameters (always parametrised: the values stay out of the string)."""
    sql, params = pair
    print(f"  SQL    : {sql}")
    print(f"  PARAMS : {params!r}")


def _result(label: str, value: object) -> None:
    """Prints a labelled result."""
    print(f"  {label}: {value!r}")


# ─────────────────────────────────────────────────────────────────────────────
# Sections
# ─────────────────────────────────────────────────────────────────────────────
def section_1_crud(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the basic CRUD: add (wide RETURNING), add_all, update, delete, first, all."""
    _section(1, "CRUD - add, add_all, update, delete, first, all")

    _step(
        "add(): inserts, and RETURNING fills in the auto PK AND the default_factory (public_id, created_at)"
    )
    author = ExAuthor(name="Autora Demo")
    print(f"  Before the INSERT: id={author.id!r} (no PK yet)")
    session.add(author)
    print(f"  After the INSERT : id={author.id!r}  public_id={author.public_id!r}")
    print(f"  created_at filled in by default_factory: {author.created_at!r}")

    _step("update(): rewrites the non-PK columns, filtering by the instance's PK")
    author.name = "Autora Demo (editada)"
    session.update(author)
    reloaded = session.first(SnakeQuery(ExAuthor).filter(ExAuthor.id == author.id))
    _result("name after update", reloaded.name if reloaded else None)

    _step("delete(): deletes the instance's row (we leave the graph as it was)")
    session.delete(author)
    _result(
        "does it still exist?",
        session.exists(SnakeQuery(ExAuthor).filter(ExAuthor.id == author.id)),
    )

    _step("all(): fetches every row as typed instances of the model")
    _sql(SnakeQuery(ExPublisher).to_sql(dialect))
    publishers = session.all(SnakeQuery(ExPublisher))
    _result("publishers", [p.name for p in publishers])


def section_2_filters(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the filters: comparators, in_, like, is_null, == None, and composition with &/|/~."""
    _section(2, "Filters - comparators, in_, like, is_null, == None, & | ~")

    _step("Comparator + like + composition with & (AND)")
    query = SnakeQuery(ExBook).filter(
        (ExBook.price > Decimal("14.00")) & ExBook.title.like("%a%")
    )
    _sql(query.to_sql(dialect))
    _result("titles", [b.title for b in session.all(query)])

    _step("in_() over a set of values")
    pub_query = SnakeQuery(ExPublisher).filter(ExPublisher.country_code.in_(["ES"]))
    _sql(pub_query.to_sql(dialect))
    _result("Spanish publishers", [p.name for p in session.all(pub_query)])

    _step("== None => IS NULL (not `= NULL`, which in SQL is always false)")
    query = SnakeQuery(ExBook).filter(ExBook.page_count == None)  # noqa: E711 - this is the whole point
    _sql(query.to_sql(dialect))
    _result("books with no page count", [b.title for b in session.all(query)])

    _step("~ (NOT) and | (OR): page count known AND (cheap OR expensive)")
    query = SnakeQuery(ExBook).filter(
        ~ExBook.page_count.is_null()
        & ((ExBook.price < Decimal("13.00")) | (ExBook.price > Decimal("50.00")))
    )
    _sql(query.to_sql(dialect))
    _result("titles", [b.title for b in session.all(query)])


def section_3_ordering(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows order_by (asc/desc), limit, offset and distinct()."""
    _section(3, "Ordering, limit, offset, distinct")

    _step("order_by(desc) + limit + offset")
    query = SnakeQuery(ExBook).order_by(ExBook.price.desc()).limit(2).offset(1)
    _sql(query.to_sql(dialect))
    _result(
        "2 books after the most expensive one",
        [(b.title, str(b.price)) for b in session.all(query)],
    )

    _step(
        "distinct(): collapses duplicates (here, the country codes present in publishers)"
    )
    pub_query = (
        SnakeQuery(ExPublisher).distinct().order_by(ExPublisher.country_code.asc())
    )
    _sql(pub_query.to_project_sql(dialect, [ExPublisher.country_code]))
    rows = session.select(pub_query, ExPublisher.country_code)
    _result("countries with a publisher (no repeats)", [row[0] for row in rows])


def section_4_deep_navigation(session: SnakeSession, dialect: SnakeDialect) -> None:
    """THE JEWEL: filter through a typed deep chain and see the SQL with every one of its JOINs."""
    _section(4, "Typed deep navigation - the jewel")

    _step(
        "ExPrinting.edition.book.publisher.country.name - composite FK -> simple -> simple -> simple"
    )
    query = SnakeQuery(ExPrinting).filter(
        ExPrinting.edition.book.publisher.country.name == "España"
    )
    _sql(query.to_sql(dialect))
    printings = session.all(query)
    _result("print runs (copies) published in Spain", [p.copies for p in printings])


def section_5_include(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows include() to-one (LEFT JOIN), to-many (select-in) and the SnakeRelationshipNotLoaded guard."""
    _section(5, "include() - to-one (LEFT JOIN), to-many (select-in), guard")

    _step(
        "include() to-one: loads ExBook + its ExPublisher in the SAME query (LEFT JOIN)"
    )
    query = (
        SnakeQuery(ExBook)
        .include(ExBook.publisher)
        .filter(ExBook.title == "Don Quixote")
    )
    _sql(query.to_include_sql(dialect))
    book = session.all(query)[0]
    _result("book and its publisher", (book.title, book.publisher.name))

    _step(
        "include() to-many: loads every ExPublisher with its list of ExBook (a separate select-in)"
    )
    publishers = session.all(SnakeQuery(ExPublisher).include(ExPublisher.books))
    for publisher in publishers:
        _result(publisher.name, [b.title for b in publisher.books])

    _step(
        "Without include(): reaching the relationship on the instance fires the guard (anti N+1)"
    )
    lone = session.all(SnakeQuery(ExBook).filter(ExBook.title == "Don Quixote"))[0]
    try:
        _ = lone.publisher
    except SnakeRelationshipNotLoaded as error:
        _result("SnakeRelationshipNotLoaded (expected)", str(error))


def section_6_collections(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the collection operations: any, ~any, nested any, count, avg, sum_, count==0."""
    _section(6, "Collections - any, ~any, nested any, count, avg, sum_, count==0")

    _step(
        ".any(): publishers with AT LEAST one book (a correlated EXISTS, it does NOT multiply rows)"
    )
    query = SnakeQuery(ExPublisher).filter(ExPublisher.books.any())
    _sql(query.to_sql(dialect))
    _result("with at least one book", [p.name for p in session.all(query)])

    _step("~.any(cond): publishers with NO expensive book at all (> 50)")
    query = SnakeQuery(ExPublisher).filter(
        ~ExPublisher.books.any(ExBook.price > Decimal("50.00"))
    )
    _sql(query.to_sql(dialect))
    _result("with no expensive book", [p.name for p in session.all(query)])

    _step(
        "NESTED .any(): countries with a publisher that has an expensive book (an any inside an any)"
    )
    country_query = SnakeQuery(ExCountry).filter(
        ExCountry.publishers.any(ExPublisher.books.any(ExBook.price > Decimal("50.00")))
    )
    _sql(country_query.to_sql(dialect))
    _result(
        "countries with an expensive bestseller",
        [c.name for c in session.all(country_query)],
    )

    _step(
        ".count() > 1: publishers with more than one book (a correlated scalar subquery)"
    )
    query = SnakeQuery(ExPublisher).filter(ExPublisher.books.count() > 1)
    _sql(query.to_sql(dialect))
    _result("with >1 book", [p.name for p in session.all(query)])

    _step(".avg()/.sum_(): publishers with an average price > 20 and a price sum > 50")
    query = SnakeQuery(ExPublisher).filter(
        (ExPublisher.books.avg(ExBook.price) > 20.0)
        & (ExPublisher.books.sum_(ExBook.price) > Decimal("50.00"))
    )
    _sql(query.to_sql(dialect))
    _result("'premium' publishers", [p.name for p in session.all(query)])

    _step(
        ".count() == 0: publishers with NO books (they all have some here, so an empty list)"
    )
    query = SnakeQuery(ExPublisher).filter(ExPublisher.books.count() == 0)
    _sql(query.to_sql(dialect))
    _result("with no books", [p.name for p in session.all(query)])


def section_7_count_exists(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the session aggregates count() and exists()."""
    _section(7, "Session count() and exists()")

    _step("count(): how many books match (COUNT(*), it honours filters and JOINs)")
    query = SnakeQuery(ExBook)
    _sql(query.to_count_sql(dialect))
    _result("total books", session.count(query))

    _step("exists(): is there any book of more than 1000 pages?")
    query = SnakeQuery(ExBook).filter(ExBook.page_count > 1000)
    _sql(query.to_exists_sql(dialect))
    _result("any doorstopper?", session.exists(query))


def section_8_projection(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows select(): columns, aggregates, deep navigation, and group_by + having."""
    _section(8, "Projection - select(), aggregates, navigation, group_by + having")

    _step("select() of columns: it gives back typed TUPLES, not instances of the model")
    query = SnakeQuery(ExBook).order_by(ExBook.price.asc())
    _sql(query.to_project_sql(dialect, [ExBook.title, ExBook.price]))
    _result(
        "(title, price)",
        [(t, str(p)) for t, p in session.select(query, ExBook.title, ExBook.price)],
    )

    _step("select() with deep navigation: the parent's column travels through the JOIN")
    query = SnakeQuery(ExBook).order_by(ExBook.title.asc())
    _sql(query.to_project_sql(dialect, [ExBook.publisher.name, ExBook.title]))
    rows = session.select(query, ExBook.publisher.name, ExBook.title)
    _result("(publisher, title)", rows)

    _step(
        "select() with an aggregate + group_by + having: publishers with more than one book"
    )
    query = SnakeQuery(ExBook).group_by(ExBook.publisher_id).having(count() > 1)
    _sql(query.to_project_sql(dialect, [ExBook.publisher_id, count()]))
    _result(
        "(publisher_id, book count)",
        session.select(query, ExBook.publisher_id, count()),
    )


def section_9_annotate(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows annotate() with @snake_result and the obj.aggregate.<name> escape hatch (with a cast)."""
    _section(9, "annotate() - typed @snake_result + escape hatch with a cast")

    # The collection aggregates have different types (count->int, avg->float, max->Decimal), so they
    # are declared separately (a dict would merge them into `object`). The order of `to_annotate_sql`
    # mirrors the order of PublisherStats' scalars: book_count, avg_price, max_price.
    book_count = ExPublisher.books.count()
    avg_price = ExPublisher.books.avg(ExBook.price)
    max_price = ExPublisher.books.max_(ExBook.price)
    query = SnakeQuery(ExPublisher).order_by(ExPublisher.name.asc())

    _step("annotate(): base row (ExPublisher) + typed scalars, grouping by the PK")
    _sql(query.to_annotate_sql(dialect, [book_count, avg_price, max_price]))
    stats = session.annotate(
        query,
        PublisherStats,
        book_count=book_count,
        avg_price=avg_price,
        max_price=max_price,
    )
    for row in stats:
        print(
            f"  {row.publisher.name:10s} -> books={row.book_count}"
            f"  mean={row.avg_price!r} (float)  max={row.max_price!r} (Decimal)"
        )

    _step(
        "Escape hatch: obj.aggregate.<name> gives back object -> it DEMANDS an explicit cast()"
    )
    first = stats[0]
    raw = first.publisher.aggregate.book_count  # static type: object (never Any)
    via_hatch = cast("int", raw)
    _result(f"{first.publisher.name} via the escape hatch (cast to int)", via_hatch)


def section_10_bulk_writes(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows bulk writing: update_where with arithmetic (col = col + x) and delete_where."""
    _section(10, "Bulk writing - update_where (arithmetic) and delete_where")

    _step(
        "update_where(): raises the price of Springer's books by 1.00 (col = col + 1)"
    )
    springer = session.all(
        SnakeQuery(ExPublisher).filter(ExPublisher.name == "Springer")
    )[0]
    query = SnakeQuery(ExBook).filter(ExBook.publisher_id == springer.id)
    _sql(query.to_update_sql(dialect, {"price": ExBook.price + Decimal("1.00")}))
    affected = session.update_where(
        query, [(ExBook.price, ExBook.price + Decimal("1.00"))]
    )
    _result("rows updated", affected)

    _step("delete_where(): deletes temporary join rows created on the fly")
    temp = ExAuthor(name="Temporary, to be deleted")
    session.add(temp)
    author_query = SnakeQuery(ExAuthor).filter(
        ExAuthor.name == "Temporary, to be deleted"
    )
    _sql(author_query.to_delete_sql(dialect))
    _result("rows deleted", session.delete_where(author_query))


def section_11_upsert(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows upsert(): DO UPDATE (with update=) and DO NOTHING (without update=)."""
    _section(11, "upsert() - DO UPDATE and DO NOTHING")

    _step(
        "upsert with update=: if the country already exists, it rewrites its name (DO UPDATE)"
    )
    country = ExCountry(code="ES", name="Kingdom of Spain")
    session.upsert(country, on_conflict=[ExCountry.code], update=[ExCountry.name])
    reloaded = session.first(SnakeQuery(ExCountry).filter(ExCountry.code == "ES"))
    _result("name of ES after DO UPDATE", reloaded.name if reloaded else None)

    _step(
        "upsert without update=: if it already exists, it does NOT touch the row (DO NOTHING)"
    )
    country = ExCountry(code="ES", name="THIS MUST NOT BE WRITTEN")
    session.upsert(country, on_conflict=[ExCountry.code])
    reloaded = session.first(SnakeQuery(ExCountry).filter(ExCountry.code == "ES"))
    _result(
        "name of ES after DO NOTHING (untouched)", reloaded.name if reloaded else None
    )


def section_12_subquery(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the scalar subquery: in_(query.as_scalar(col))."""
    _section(12, "Subquery - in_(query.as_scalar(col))")

    _step(
        "Books from Spanish publishers, resolved with IN (SELECT id FROM ex_publishers WHERE ...)"
    )
    spanish_ids = (
        SnakeQuery(ExPublisher)
        .filter(ExPublisher.country_code == "ES")
        .as_scalar(ExPublisher.id)
    )
    query = (
        SnakeQuery(ExBook)
        .filter(ExBook.publisher_id.in_(spanish_ids))
        .order_by(ExBook.title.asc())
    )
    _sql(query.to_sql(dialect))
    _result("Spanish books", [b.title for b in session.all(query)])


def section_13_m2m(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the many-to-many by navigating through the EXPLICIT join table."""
    _section(13, "Many-to-many - navigating the explicit join table")

    _step("Cervantes' join rows (it navigates ExBookAuthor.author) + its book included")
    query = (
        SnakeQuery(ExBookAuthor)
        .filter(ExBookAuthor.author.name == "Miguel de Cervantes")
        .include(ExBookAuthor.book)
    )
    _sql(query.to_include_sql(dialect))
    links = session.all(query)
    _result(
        "(title, royalty)",
        [(link.book.title, str(link.royalty)) for link in links],
    )


def section_14_composite(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows composite PK/FK: a composite JOIN and a composite include() (select-in by tuple)."""
    _section(14, "Composite PK/FK - composite JOIN and composite include")

    # It navigates as far as `title`, which has a SQL name override (`name="book_title"`): the path
    # is written with the Python ATTRIBUTE and the SQL comes out with the column's name.
    _step(
        "Composite JOIN: print runs of 'Don Quixote', AND of the composite FK's two pairs"
    )
    query = (
        SnakeQuery(ExPrinting)
        .filter(ExPrinting.edition.book.title == "Don Quixote")
        .order_by(ExPrinting.copies.asc())
    )
    _sql(query.to_sql(dialect))
    _result("copies per print run", [p.copies for p in session.all(query)])

    _step(
        "Composite include(): every ExEdition with its list of ExPrinting (select-in by TUPLE)"
    )
    editions = session.all(
        SnakeQuery(ExEdition)
        .include(ExEdition.printings)
        .order_by(ExEdition.edition_no.asc())
    )
    for edition in editions:
        _result(
            f"edition {edition.edition_no} ({edition.note})",
            [p.copies for p in edition.printings],
        )


def section_15_guards(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the GUARDS as safety features: each one is a CLEAR error, not a silent bug."""
    _section(15, "Guards - safety features, caught and displayed")

    _step(
        "delete_where with NO filter => SnakeUnsupportedFeature (the table is not wiped by accident)"
    )
    try:
        session.delete_where(SnakeQuery(ExBook))
    except SnakeUnsupportedFeature as error:
        _result("SnakeUnsupportedFeature (expected)", str(error))

    _step(
        "annotate with names that do not match => SnakeEmitError (validated BEFORE emitting SQL)"
    )
    try:
        session.annotate(
            SnakeQuery(ExPublisher),
            PublisherStats,
            book_count=ExPublisher.books.count(),
            wrong_name=ExPublisher.books.count(),
        )
    except SnakeEmitError as error:
        _result("SnakeEmitError (expected)", str(error))

    _step(
        "A TYPING guard (not a runtime one): the commented line does NOT compile under mypy"
    )
    print("  # does not compile:  ExCountry.publishers.name")
    print(
        "  # (publishers is to-many => class access gives SnakeCollection, with no child columns)"
    )


def section_16_coercion(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows coercion: a projected UUID column comes back as uuid.UUID, not as str."""
    _section(16, "Coercion - a UUID column comes back as uuid.UUID, not str")

    _step(
        "select() of a UUID column: psycopg2 gives it as str; the ORM coerces it to the declared type"
    )
    query = SnakeQuery(ExAuthor).filter(ExAuthor.name == "Thomas H. Cormen")
    _sql(query.to_project_sql(dialect, [ExAuthor.public_id]))
    rows = session.select(query, ExAuthor.public_id)
    value = rows[0][0]
    _result("value", value)
    _result("type(value).__name__", type(value).__name__)


def section_17_server_default(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows server_default: the DB puts in created_at (NOW) and row_uuid (UUID_V4); the object gets them."""
    _section(17, "server_default - the value is put in by the SERVER (NOW, UUID_V4)")

    _step(
        "add() of a publisher with NO created_at or row_uuid: the DB fills them and RETURNING brings them"
    )
    publisher = ExPublisher(name="Ephemeral Press", country_code="ES")
    print(
        f"  Before the INSERT: created_at={publisher.created_at!r}  row_uuid={publisher.row_uuid!r}"
    )
    session.add(publisher)
    print(f"  After the INSERT : created_at={publisher.created_at!r}")
    print(
        f"                     row_uuid={publisher.row_uuid!r} (uuid.UUID, generated by Postgres)"
    )

    _step(
        "The DDL the migrations emit creates the column with its DEFAULT (translated by the dialect)"
    )
    print(f"  DDL: {emit_create_table(snake_table(ExPublisher), dialect)}")

    session.delete(publisher)  # we leave the graph as it was


def section_18_explicit_join(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the EXPLICIT JOIN to a collection: the child's rows, MULTIPLIED, against `.any()`."""
    _section(
        18, "Explicit JOIN to a collection - the child's rows (they multiply), vs any()"
    )

    _step(
        ".any(): publishers with AT LEAST one book -> ONE row per publisher (EXISTS, it does not multiply)"
    )
    exists_query = SnakeQuery(ExPublisher).filter(ExPublisher.books.any())
    _sql(exists_query.to_sql(dialect))
    _result(
        "publishers (one per publisher)",
        sorted(p.name for p in session.all(exists_query)),
    )

    _step(
        ".join(): the child's ROWS, flat and MULTIPLIED -> one row per (publisher, book)"
    )
    joined = SnakeQuery(ExPublisher).join(ExPublisher.books)
    joined = joined.order_by(ExPublisher.name.asc(), joined.right.title.asc())
    _sql(joined.to_project_sql(dialect, [ExPublisher.name, joined.right.title]))
    rows = session.select(joined, ExPublisher.name, joined.right.title)
    _result("(publisher, title) - Anaya and Springer come out twice", rows)

    _step(
        "LEFT join: it includes the publisher with NO books, the child's title left NULL "
        "(they all have some here, so nothing changes)"
    )
    left = SnakeQuery(ExPublisher).join(ExPublisher.books, how=SnakeJoin.LEFT)
    _sql(left.to_project_sql(dialect, [ExPublisher.name, left.right.title]))

    _step(
        "The type forbids it: session.all(joined) does NOT compile - hydrating multiplied rows "
        "would give back the same parent N times"
    )
    print(
        "  # no compila:  session.all(SnakeQuery(ExPublisher).join(ExPublisher.books))"
    )
    print(
        "  # (.join() gives back SnakeJoinedQuery: it only projects tuples, it does not hydrate models)"
    )


class _CountingDriver:
    """Wraps a driver and COUNTS the `fetch_all`s, so section 19 can show 'one query per level'."""

    def __init__(self, inner: PsycopgDriver) -> None:
        self._inner = inner
        self.fetch_count = 0

    def fetch_all(self, sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
        self.fetch_count += 1
        return self._inner.fetch_all(sql, params)

    def fetch_iter(
        self, sql: str, params: Sequence[object], *, chunk: int = 1000
    ) -> Iterator[tuple[object, ...]]:
        """A test double: there is no engine behind it to stream from, so it yields whatever
        `fetch_all` gives back. The degradation is written HERE, in plain sight, and is not something
        the framework does."""
        yield from self.fetch_all(sql, params)

    def execute(self, sql: str, params: Sequence[object]) -> int:
        return self._inner.execute(sql, params)

    @property
    def last_insert_id(self) -> int:
        return 0

    def commit(self) -> None:
        self._inner.commit()

    def rollback(self) -> None:
        self._inner.rollback()

    def savepoint(self, name: str) -> None:
        self._inner.savepoint(name)

    def release_savepoint(self, name: str) -> None:
        self._inner.release_savepoint(name)

    def rollback_to_savepoint(self, name: str) -> None:
        self._inner.rollback_to_savepoint(name)

    def close(self) -> None:
        self._inner.close()


def section_19_nested_include(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows the NESTED include with SnakePrefetch: to-many -> to-many with ONE query per level."""
    _section(
        19, "NESTED include() - SnakePrefetch (to-many -> to-many), one query per LEVEL"
    )

    _step(
        "SnakePrefetch(ExCountry.publishers).then(ExPublisher.books): country -> publishers -> books"
    )
    print(
        "  # A collection does not expose the child's relationships (ExCountry.publishers.books does NOT exist):"
    )
    print("  # the nested chain is DECLARED with an object, not by navigating.")

    # A connection of its own is wrapped in a counting driver, so as to exhibit the number of queries.
    counting = _CountingDriver(PsycopgDriver.connect(dsn()))
    try:
        nested_session = SnakeSession(counting, dialect)
        countries = nested_session.all(
            SnakeQuery(ExCountry).include(
                SnakePrefetch(ExCountry.publishers).then(ExPublisher.books)
            )
        )
        for country in countries:
            for publisher in country.publishers:
                _result(
                    f"{country.name} -> {publisher.name}",
                    [book.title for book in publisher.books],
                )
        _result(
            "queries emitted (1 root + 1 per level; NOT one per parent -> no N+1)",
            counting.fetch_count,
        )
    finally:
        counting.close()

    _step(
        ".filter() on the prefetch: only the EXPENSIVE books (> 40); a publisher with NONE still COMES, with []"
    )
    print(
        "  # prefetch.filter(cond) narrows WHICH CHILDREN load, without dropping parents (!= query.filter):"
    )
    print("  # a parent with no matching children gets [] but STILL comes.")
    filtered = session.all(
        SnakeQuery(ExCountry).include(
            SnakePrefetch(ExCountry.publishers)
            .then(ExPublisher.books)
            .filter(ExBook.price > Decimal("40.00"))
        )
    )
    by_publisher = {
        publisher.name: sorted(book.title for book in publisher.books)
        for country in filtered
        for publisher in country.publishers
    }
    for name in sorted(by_publisher):
        _result(f"expensive books of {name}", by_publisher[name])


def section_20_inheritance(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows column inheritance: ExTag and ExNote inherit id + created_at from a base."""
    _section(20, "Column inheritance - a shared abstract base (ExTimestamped)")

    _step(
        "ExTag and ExNote do NOT declare id or created_at: they INHERIT them from ExTimestamped (a base with no table)"
    )
    # The inherited columns come out BEFORE the class's own (the compiler walks the MRO base->child).
    _result(
        "columns inherited by ex_tags",
        [column.name for column in snake_table(ExTag).columns],
    )
    _result(
        "columns inherited by ex_notes",
        [column.name for column in snake_table(ExNote).columns],
    )

    _step(
        "add() of an ExTag: the DB fills in id (auto) and created_at (server_default), both INHERITED"
    )
    tag = ExTag(
        label="new arrival"
    )  # only its own column is passed; the rest it inherits / the DB puts in
    print(f"  Before the INSERT: id={tag.id!r}  created_at={tag.created_at!r}")
    session.add(tag)
    print(f"  After the INSERT : id={tag.id!r}  created_at={tag.created_at!r}")
    _result(
        "inherited columns filled in by the DB",
        (isinstance(tag.id, int), isinstance(tag.created_at, datetime)),
    )


def section_21_views(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows a read-only VIEW: querying it, navigating both ways, and the write guard."""
    _section(21, "Views - a READ-ONLY model, navigable in both directions")

    _step(
        "all(ExCatalogEntry): the view is queried like a model and gives back TYPED rows"
    )
    catalog_query = SnakeQuery(ExCatalogEntry).order_by(ExCatalogEntry.book_title.asc())
    _sql(catalog_query.to_sql(dialect))
    catalog = session.all(catalog_query)
    _result(
        "(title, price) of the catalogue",
        [(row.book_title, str(row.price)) for row in catalog],
    )

    _step(
        "MODEL -> VIEW navigation: include(ExPublisher.catalog) loads the view as a to-many (select-in)"
    )
    publishers = session.all(
        SnakeQuery(ExPublisher)
        .include(ExPublisher.catalog)
        .order_by(ExPublisher.name.asc())
    )
    for publisher in publishers:
        _result(
            f"catalogue of {publisher.name}",
            sorted(entry.book_title for entry in publisher.catalog),
        )

    _step(
        "VIEW -> MODEL navigation: include(ExCatalogEntry.publisher) brings each row's publisher"
    )
    entry_query = (
        SnakeQuery(ExCatalogEntry)
        .include(ExCatalogEntry.publisher)
        .filter(ExCatalogEntry.book_title == "Don Quixote")
    )
    _sql(entry_query.to_include_sql(dialect))
    entry = session.all(entry_query)[0]
    _result("publisher of 'Don Quixote' (view -> model)", entry.publisher.name)

    _step(
        "The read-only guard: session.add(view) does NOT compile (a type lock) and fails at runtime"
    )
    print(
        "  # does not compile:  session.add(ExCatalogEntry(...))  <- it wants a SnakeModel, and a view is not one"
    )
    try:
        session.add(cast("Any", catalog[0]))
    except SnakeUnsupportedFeature as error:
        _result("SnakeUnsupportedFeature (expected)", str(error))


def section_22_db_functions(session: SnakeSession, dialect: SnakeDialect) -> None:
    """Shows session.call(): it calls a database FUNCTION and maps its rows to a DECLARED shape."""
    _section(
        22,
        "Database functions - session.call() to a @snake_row (a DECLARED contract, not a verified one)",
    )

    _step(
        "call(): queries the ex_book_stats(min_price) function and maps its rows to a @snake_row"
    )
    args: list[object] = [Decimal("0.00")]
    # `session.call` emits `SELECT * FROM name(placeholders)` with the ARGS parametrised (user data),
    # and coerces every column to the type of the declared field (`total` is float <- NUMERIC).
    print(f"  SQL    : SELECT * FROM ex_book_stats({dialect.placeholder(1)})")
    print(f"  PARAMS : {args!r}")
    rows = session.call("ex_book_stats", args, into=BookStats)
    for row in rows:
        _result(f"publisher {row.publisher_id}", (row.book_count, row.total))
    print(
        "  # HONESTY: a function is OPAQUE SQL. The ORM does NOT check that it exists, nor what it returns:"
    )
    print(
        "  # YOU declare the shape (@snake_row), I hydrate it. Exactly as honest as a raw SELECT."
    )


_SECTIONS = (
    section_1_crud,
    section_2_filters,
    section_3_ordering,
    section_4_deep_navigation,
    section_5_include,
    section_6_collections,
    section_7_count_exists,
    section_8_projection,
    section_9_annotate,
    section_10_bulk_writes,
    section_11_upsert,
    section_12_subquery,
    section_13_m2m,
    section_14_composite,
    section_15_guards,
    section_16_coercion,
    section_17_server_default,
    section_18_explicit_join,
    section_19_nested_include,
    section_20_inheritance,
    section_21_views,
    section_22_db_functions,
)


def main() -> None:
    """Entry point: connects, prepares the schema and walks the 22 sections against Postgres."""
    snake_link()  # resolves the relationships (needed before using FKs, includes and the DDL)
    register_uuid_write_adapter()  # teaches psycopg2 to WRITE uuid.UUID (reading still gives str)

    driver = PsycopgDriver.connect(dsn())
    dialect = PostgresDialect()
    try:
        create_schema(driver, dialect)
        session = SnakeSession(driver, dialect)
        seed(session)
        session.commit()

        print(
            "\nSnakeORM - a TOUR of the API over the publishing domain (a real Postgres)"
        )
        for section in _SECTIONS:  # 22 numbered sections
            section(session, dialect)
        session.commit()
        print("\n" + "=" * _WIDTH)
        print(" END OF THE TOUR - every section executed against a real Postgres.")
        print("=" * _WIDTH)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
