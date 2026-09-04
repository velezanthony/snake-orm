"""Demonstration PUBLISHING domain: it exercises the WHOLE syntax of SnakeORM.

This module is living documentation. Every model teaches one piece of the type system and of the
metadata: autoincrement and explicit PK, COMPOSITE PK and FK, many-to-many with an EXPLICIT join
table, UUID/Decimal columns, literal `default` vs `default_factory`, `name=` (override of the SQL
name), `db_comment`, indexes (`SnakeIndexes`) and to-one / to-many relationships on both sides.

The domain graph (every table prefixed with `ex_` and every class prefixed with `Ex` so they do not
collide with the GLOBAL registry that the tests share):

    ExCountry (PK str)  1──*  ExPublisher (PK auto)  1──*  ExBook (PK auto)
                                                             │  1──*  ExEdition (PK compuesta)
                                                             │              1──*  ExPrinting (FK compuesta)
                                                             └──*  ExBookAuthor  *──┐
                                                                                    ExAuthor (PK auto)

The deep chain for the "crown jewel" of the typing (fully typed navigation, no `Any`):

    ExPrinting.edition.book.publisher.country.name   # composite FK → simple → simple → simple → column

The DDL (`create_schema`) and the seed (`seed`) are generated from the compiled metadata using the
emitters of `snakeorm.migration`: NO hand-written SQL. That way the example also demonstrates that
the metadata is the single source of truth.
"""

from __future__ import annotations

from snakeorm import SnakeUtc, snake_datetimetz

import uuid
from decimal import Decimal

import psycopg2.extensions

from snakeorm.decorators import (
    SnakeResult,
    SnakeRow,
    snake_model,
    snake_result,
    snake_row,
    snake_table,
    snake_view,
)
from snakeorm.dialects import SnakeDialect
from snakeorm.drivers import SnakeDriver
from snakeorm.core.exceptions import SnakeRegistryError
from snakeorm.fields import (
    SnakeColumn,
    SnakeIndex,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_column,
    snake_int,
    snake_str,
    snake_to_many,
    snake_to_one,
)
from snakeorm.metadata import SnakeFkAction, SnakeServerDefault
from snakeorm.migration import (
    emit_add_foreign_key,
    emit_create_index,
    emit_create_table,
    emit_create_view,
)
from snakeorm.model import SnakeModel, SnakeView
from snakeorm.registry import registry
from snakeorm.session import SnakeSession


# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────
@snake_model(table="ex_countries")
class ExCountry(SnakeModel):
    """Country. EXPLICIT non-autoincrement PK (an ISO code, chosen by the user)."""

    code: SnakeColumn[str] = snake_str(primary_key=True)
    name: SnakeColumn[str] = snake_str()
    publishers: SnakeToMany[ExPublisher] = snake_to_many("country")


@snake_model(table="ex_publishers")
class ExPublisher(SnakeModel):
    """Publisher. AUTOINCREMENT PK (`snake_auto`), `unique`, literal `default` and `db_comment`."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str(
        unique=True, db_comment="Trading name of the publishing house"
    )
    # `default=True` is a LITERAL: it travels to the DDL as `DEFAULT TRUE` (the dialect formats it).
    active: SnakeColumn[bool] = snake_column(default=True)
    # `server_default`: the SERVER supplies the value (an AGNOSTIC enum that the dialect translates:
    # NOW→CURRENT_TIMESTAMP, UUID_V4→gen_random_uuid()). The column is EXCLUDED from __init__ and the
    # INSERT; the wide RETURNING brings it back into the in-memory object. No Postgres jargon here.
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )
    row_uuid: SnakeColumn[uuid.UUID] = snake_column(
        server_default=SnakeServerDefault.UUID_V4
    )
    country_code: SnakeColumn[str] = snake_str()
    # SIMPLE FK with a referential action: if the country is deleted, its publishers go with it.
    country: SnakeToOne[ExCountry] = snake_to_one(
        country_code, on_delete=SnakeFkAction.CASCADE
    )
    books: SnakeToMany[ExBook] = snake_to_many("publisher")
    # To-many towards a read-only VIEW (`ExCatalogEntry`): the inverse of the view's `publisher` FK.
    # Navigation works in both directions even though the view carries no constraints.
    catalog: SnakeToMany[ExCatalogEntry] = snake_to_many("publisher")


@snake_model(table="ex_authors")
class ExAuthor(SnakeModel):
    """Author. A `UUID` column (coercion) and two `default_factory` (importable callables)."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    # `default_factory` is a PYTHON callable: it runs when the object is built, it never touches the
    # DDL. `uuid.uuid4` generates a fresh value per instance; `unique` protects it in the database.
    public_id: SnakeColumn[uuid.UUID] = snake_column(
        unique=True, default_factory=uuid.uuid4
    )
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(default_factory=SnakeUtc.now)
    book_authors: SnakeToMany[ExBookAuthor] = snake_to_many("author")


@snake_model(table="ex_books")
class ExBook(SnakeModel):
    """Book. `name=` (SQL override), `db_comment`, `index=`, `Decimal`, nullable (`int | None`)."""

    id: SnakeColumn[int] = snake_auto()
    # `name=` renames the SQL column: the Python attribute is `title`, the column is `book_title`.
    title: SnakeColumn[str] = snake_str(
        name="book_title", index=True, db_comment="Title of the book"
    )
    isbn: SnakeColumn[str] = snake_str(unique=True)
    price: SnakeColumn[Decimal] = snake_column()
    # `int | None` in the annotation ⇒ NULLABLE column (the compiler infers it from the type).
    page_count: SnakeColumn[int | None] = snake_int()
    publisher_id: SnakeColumn[int] = snake_int()
    publisher: SnakeToOne[ExPublisher] = snake_to_one(
        publisher_id, on_delete=SnakeFkAction.CASCADE
    )
    editions: SnakeToMany[ExEdition] = snake_to_many("book")
    book_authors: SnakeToMany[ExBookAuthor] = snake_to_many("book")

    # COMPOSITE UNIQUE index: two different books from one same publisher do not share a title.
    # It references the column DESCRIPTORS directly (typed, no magic strings). Note: the column
    # references its real SQL name, so `title` goes in as "book_title".
    SnakeIndexes = [SnakeIndex(publisher_id, title, unique=True)]


@snake_model(table="ex_editions")
class ExEdition(SnakeModel):
    """Edition. COMPOSITE PK `(book_id, edition_no)`; `book_id` is also an FK to ExBook."""

    book_id: SnakeColumn[int] = snake_int(primary_key=True)
    edition_no: SnakeColumn[int] = snake_int(primary_key=True)
    note: SnakeColumn[str] = snake_str()
    book: SnakeToOne[ExBook] = snake_to_one(book_id, on_delete=SnakeFkAction.CASCADE)
    printings: SnakeToMany[ExPrinting] = snake_to_many("edition")


@snake_model(table="ex_printings")
class ExPrinting(SnakeModel):
    """Printing. COMPOSITE FK towards the composite PK of ExEdition (two columns, same order)."""

    id: SnakeColumn[int] = snake_auto()
    edition_book_id: SnakeColumn[int] = snake_int()
    edition_no: SnakeColumn[int] = snake_int()
    copies: SnakeColumn[int] = snake_int()
    # COMPOSITE FK: the pairing is POSITIONAL against (book_id, edition_no) of ExEdition.
    edition: SnakeToOne[ExEdition] = snake_to_one(
        edition_book_id, edition_no, on_delete=SnakeFkAction.CASCADE
    )


@snake_model(table="ex_book_authors")
class ExBookAuthor(SnakeModel):
    """EXPLICIT join table (many-to-many): composite PK of BOTH FKs + a column of its own."""

    book_id: SnakeColumn[int] = snake_int(primary_key=True)
    author_id: SnakeColumn[int] = snake_int(primary_key=True)
    # A column BELONGING to the M2M relationship (what justifies declaring it a model, not magic).
    royalty: SnakeColumn[Decimal] = snake_column()
    book: SnakeToOne[ExBook] = snake_to_one(book_id, on_delete=SnakeFkAction.CASCADE)
    author: SnakeToOne[ExAuthor] = snake_to_one(
        author_id, on_delete=SnakeFkAction.CASCADE
    )


class ExTimestamped(SnakeModel):
    """Shared ABSTRACT base (it carries NO @snake_model: it is not a table and is not registered).

    It groups two columns that repeat across many tables —an autoincrement `id` and a `created_at`
    put there by the server— so they can be inherited without being duplicated. The compiler walks
    the MRO, so the models that inherit from it end up with these columns BEFORE their own. It is
    the good old mixin pattern, but fully typed: `ExTag.created_at` is still `SnakeExpr[datetime]`.
    """

    id: SnakeColumn[int] = snake_auto()
    created_at: SnakeColumn[SnakeUtc] = snake_datetimetz(
        server_default=SnakeServerDefault.NOW
    )


@snake_model(table="ex_tags")
class ExTag(ExTimestamped):
    """Tag. INHERITS id + created_at from ExTimestamped; it only adds `label`."""

    label: SnakeColumn[str] = snake_str(unique=True)


@snake_model(table="ex_notes")
class ExNote(ExTimestamped):
    """Note. INHERITS id + created_at from the SAME base; it adds `body`."""

    body: SnakeColumn[str] = snake_str()


@snake_view(
    sql=(
        'SELECT p."id" AS publisher_id, b."book_title" AS book_title, b."price" AS price '
        'FROM "public"."ex_books" b '
        'JOIN "public"."ex_publishers" p ON b."publisher_id" = p."id"'
    ),
    name="ex_catalog",
)
class ExCatalogEntry(SnakeView):
    """READ-ONLY VIEW: the flattened catalog (publisher + title + price of every book).

    It is mapped like a typed model, but it is NOT written to (`session.add/update/delete` reject
    it: a TYPE lock). It is navigable in both directions: `publisher` (FK towards ExPublisher) and
    the inverse `ExPublisher.catalog` (to-many). A view's FK is NOT guaranteed by the database —the
    view's DDL emits no constraints—: navigation is pure SQL generation. Creating/altering/dropping
    it lives in the migrations (CreateView/AlterView/DropView), not in the session.
    """

    publisher_id: SnakeColumn[int] = snake_int()
    book_title: SnakeColumn[str] = snake_str()
    price: SnakeColumn[Decimal] = snake_column()
    publisher: SnakeToOne[ExPublisher] = snake_to_one(publisher_id)


@snake_result
class PublisherStats(SnakeResult[ExPublisher]):
    """TYPED container for `session.annotate()`: the base row + scalar aggregates.

    `avg_price` and `max_price` are `... | None` because `AVG`/`MAX` over zero rows are NULL (only
    `COUNT` is 0). The declared type is the source of truth for the coercion: an `AVG` that Postgres
    hands over as `Decimal` comes back as `float` because `float` is what is declared here.
    """

    publisher: ExPublisher
    book_count: int
    avg_price: float | None
    max_price: Decimal | None


@snake_row
class BookStats(SnakeRow):
    """DECLARED shape of the `ex_book_stats` function (opaque SQL): ALL fields scalar.

    Unlike `@snake_result` (which demands a base model), a `@snake_row` has no base row: it is the
    contract the user DECLARES for what they expect out of a function/procedure. The ORM hydrates
    every row into this shape and coerces the types (`total` is float even though the function
    returns NUMERIC), but it does NOT verify that the function exists nor that it returns this: you
    declare, I hydrate.
    """

    publisher_id: int
    book_count: int
    total: float


# The `ex_book_stats` DATABASE FUNCTION: OPAQUE SQL (PL/pgSQL or SQL, NOT portable) living in the
# database. `RETURNS TABLE(...)` makes it queryable with `SELECT * FROM ex_book_stats(...)`, which is
# exactly what `session.call(...)` emits. The ORM does NOT interpret its body: a declared black box.
BOOK_STATS_FUNCTION = (
    "CREATE OR REPLACE FUNCTION ex_book_stats(min_price numeric) "
    "RETURNS TABLE(publisher_id integer, book_count integer, total numeric) AS $$ "
    'SELECT b."publisher_id", COUNT(*)::integer, SUM(b."price") '
    'FROM "public"."ex_books" b '
    'WHERE b."price" >= min_price '
    'GROUP BY b."publisher_id" '
    'ORDER BY b."publisher_id" $$ LANGUAGE sql'
)


# Creation order: the tables are created first (with no inline FKs) and the FKs are added at the
# end, so the order of this list does not matter for the dependencies. The DROP uses CASCADE.
MODELS: tuple[type[SnakeModel], ...] = (
    ExCountry,
    ExPublisher,
    ExAuthor,
    ExBook,
    ExEdition,
    ExPrinting,
    ExBookAuthor,
    ExTag,
    ExNote,
)

# The VIEWS are created AFTER the tables (they depend on them) and they are read-only.
VIEWS: tuple[type[SnakeView], ...] = (ExCatalogEntry,)


# ─────────────────────────────────────────────────────────────────────────────
# Infrastructure: UUID adapter, DDL and seed
# ─────────────────────────────────────────────────────────────────────────────
def register_uuid_write_adapter() -> None:
    """Teaches psycopg2 to WRITE a `uuid.UUID` (out of the box it cannot adapt one).

    It is a WRITE-only adapter on purpose: it does NOT register the read typecaster, so Postgres
    keeps returning the UUID columns as `str`. That way the ORM's str→UUID coercion is genuinely
    exercised (were we to register the read side, psycopg2 would already return UUID and would
    prove nothing). The value travels quoted and cast (`'...'::uuid`), not crudely interpolated.
    """

    def adapt_uuid(value: uuid.UUID) -> psycopg2.extensions.AsIs:
        quoted = psycopg2.extensions.adapt(str(value))
        return psycopg2.extensions.AsIs(f"{quoted}::uuid")

    psycopg2.extensions.register_adapter(uuid.UUID, adapt_uuid)


def create_schema(driver: SnakeDriver, dialect: SnakeDialect) -> None:
    """Creates (resetting) the schema by generating the DDL from the compiled metadata.

    Three phases, like a real migration: (1) CREATE TABLE for every table, (2) ALTER TABLE ADD
    FOREIGN KEY for every to-one relationship (with its ON DELETE), (3) CREATE INDEX for every
    declared index. NO hand-written SQL: the emitters of `snakeorm.migration` translate the
    metadata. It requires `snake_link()` called beforehand (FKs are resolved in the linker).
    """
    tables = [snake_table(model) for model in MODELS]
    views = [snake_table(view) for view in VIEWS]
    references = ", ".join(
        f"{dialect.quote_ident(table.schema)}.{dialect.quote_ident(table.name)}"
        for table in tables
    )
    for view in (
        views
    ):  # the views first (they depend on the tables that are about to be recreated)
        view_ref = (
            f"{dialect.quote_ident(view.schema)}.{dialect.quote_ident(view.name)}"
        )
        driver.execute(f"DROP VIEW IF EXISTS {view_ref}", ())
    driver.execute(f"DROP TABLE IF EXISTS {references} CASCADE", ())
    for table in tables:
        driver.execute(emit_create_table(table, dialect), ())
    for table in tables:
        for relationship in table.relationships:
            if relationship.kind != "to_one":
                continue
            target = registry.table_by_name(relationship.target)
            if target is None:
                raise SnakeRegistryError(
                    f"The target '{relationship.target}' de '{table.name}."
                    f"{relationship.name}' is not registered."
                )
            driver.execute(
                emit_add_foreign_key(table, relationship, target, dialect), ()
            )
    for table in tables:
        for index in table.indexes:
            driver.execute(emit_create_index(table, index, dialect), ())
    # The VIEWS are created LAST: they depend on the tables already existing. A view emits no FK.
    for view in views:
        driver.execute(emit_create_view(view, dialect), ())
    # The database FUNCTION (opaque SQL): recreated idempotently. `session.call(...)` will query it.
    driver.execute("DROP FUNCTION IF EXISTS ex_book_stats(numeric)", ())
    driver.execute(BOOK_STATS_FUNCTION, ())


def seed(session: SnakeSession) -> None:
    """Fills a deterministic graph with `session.add` / `add_all` (RETURNING fills the auto PKs in).

    The data is chosen so that the aggregations and the JOINs can be asserted on: Anaya has 2 books,
    Springer 2, Planeta 1; only `Don Quixote` has editions and print runs.
    """
    # Countries: explicit PK (assigned by hand). add_all inserts the batch in one go.
    session.add_all(
        [
            ExCountry(code="ES", name="España"),
            ExCountry(code="DE", name="Alemania"),
        ]
    )

    # Publishers: autoincrementing PK -> the id arrives after the INSERT (RETURNING).
    anaya = session.add(ExPublisher(name="Anaya", country_code="ES"))
    planeta = session.add(ExPublisher(name="Planeta", country_code="ES"))
    springer = session.add(
        ExPublisher(name="Springer", active=False, country_code="DE")
    )

    # Books: `page_count` nullable (one goes to None), `price` Decimal, `title` with a SQL override.
    quijote = session.add(
        ExBook(
            title="Don Quixote",
            isbn="978-84-0001",
            price=Decimal("19.99"),
            page_count=863,
            publisher_id=anaya.id,
        )
    )
    novelas = session.add(
        ExBook(
            title="Novelas ejemplares",
            isbn="978-84-0002",
            price=Decimal("12.50"),
            page_count=350,
            publisher_id=anaya.id,
        )
    )
    sombra = session.add(
        ExBook(
            title="The Shadow of the Wind",
            isbn="978-84-0003",
            price=Decimal("15.00"),
            page_count=None,  # no data: the column is NULLABLE
            publisher_id=planeta.id,
        )
    )
    algorithms = session.add(
        ExBook(
            title="Introduction to Algorithms",
            isbn="978-02-0001",
            price=Decimal("60.00"),
            page_count=1312,
            publisher_id=springer.id,
        )
    )
    databases = session.add(
        ExBook(
            title="Database System Concepts",
            isbn="978-02-0002",
            price=Decimal("45.00"),
            page_count=900,
            publisher_id=springer.id,
        )
    )

    # Authors: public_id (UUID) and created_at (datetime) are filled in by their default_factory.
    cervantes = session.add(ExAuthor(name="Miguel de Cervantes"))
    zafon = session.add(ExAuthor(name="Carlos Ruiz Zafón"))
    cormen = session.add(ExAuthor(name="Thomas H. Cormen"))
    silberschatz = session.add(ExAuthor(name="Abraham Silberschatz"))

    # EXPLICIT many-to-many: every join row carries a `royalty` column of its own.
    session.add_all(
        [
            ExBookAuthor(
                book_id=quijote.id, author_id=cervantes.id, royalty=Decimal("0.10")
            ),
            ExBookAuthor(
                book_id=novelas.id, author_id=cervantes.id, royalty=Decimal("0.08")
            ),
            ExBookAuthor(
                book_id=sombra.id, author_id=zafon.id, royalty=Decimal("0.12")
            ),
            ExBookAuthor(
                book_id=algorithms.id, author_id=cormen.id, royalty=Decimal("0.15")
            ),
            ExBookAuthor(
                book_id=databases.id, author_id=silberschatz.id, royalty=Decimal("0.11")
            ),
        ]
    )

    # Editions (composite PK) and print runs (composite FK) for `Don Quixote` ONLY.
    session.add_all(
        [
            ExEdition(book_id=quijote.id, edition_no=1, note="Primera edición"),
            ExEdition(book_id=quijote.id, edition_no=2, note="Edición revisada"),
        ]
    )
    session.add_all(
        [
            ExPrinting(edition_book_id=quijote.id, edition_no=1, copies=1000),
            ExPrinting(edition_book_id=quijote.id, edition_no=1, copies=2000),
            ExPrinting(edition_book_id=quijote.id, edition_no=2, copies=1500),
        ]
    )
