"""Navigating all the way to a column carrying `name=` (an SQL name override) must work.

The `SnakePathProxy` resolved columns by their SQL name, but the user writes the name of the Python
ATTRIBUTE. With an override the two differ, and then:

    ProxyBook.author.pen_name   # the checker: SnakeExpr[str], correct
                                # the runtime: AttributeError, the SQL column is 'nom_de_plume'

Which is to say, the type LIED: it passed mypy and pyright and blew up against the database. That is
exactly the class of bug this ORM exists to make impossible. DIRECT access (`ProxyAuthor.pen_name`)
always worked, because there it is the descriptor resolving, and it does know the attribute name.

The emitted path must carry the SQL name (`nom_de_plume`), which is what goes into the `SELECT`.
"""

from __future__ import annotations

from snakeorm.decorators import snake_model
from snakeorm.dialects.postgres import PostgresDialect
from snakeorm.fields import SnakeColumn, SnakeToOne, snake_int, snake_str, snake_to_one

from snakeorm.linker.linker import snake_link
from snakeorm.model import SnakeModel
from snakeorm.query import SnakeQuery

DIALECT = PostgresDialect()


@snake_model(table="pxo_authors")
class ProxyAuthor(SnakeModel):
    """The Python attribute is `pen_name`; the SQL column is called `nom_de_plume`."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    pen_name: SnakeColumn[str] = snake_str(name="nom_de_plume")


@snake_model(table="pxo_books")
class ProxyBook(SnakeModel):
    """Book with a to-one relation to the author, so the renamed column can be navigated to."""

    id: SnakeColumn[int] = snake_int(primary_key=True)
    author_id: SnakeColumn[int] = snake_int()
    author: SnakeToOne[ProxyAuthor] = snake_to_one(author_id)


snake_link()


def test_direct_access_uses_the_sql_name() -> None:
    """Direct access already worked: the descriptor knows the SQL name of its own column."""
    assert ProxyAuthor.pen_name.path == ("nom_de_plume",)


def test_navigating_to_a_renamed_column_resolves() -> None:
    """Navigating the relation to the Python ATTRIBUTE raises nothing and yields the SQL path."""
    assert ProxyBook.author.pen_name.path == ("author", "nom_de_plume")


def test_navigating_by_the_sql_name_also_resolves() -> None:
    """For backward compatibility the SQL name still resolves: columns with no override use it."""
    assert ProxyBook.author.id.path == ("author", "id")


def test_the_emitted_sql_uses_the_sql_name() -> None:
    """The JOIN qualifies the column with its SQL name, not with the Python attribute's."""
    sql, params = (
        SnakeQuery(ProxyBook)
        .filter(ProxyBook.author.pen_name == "Alcott")
        .to_sql(DIALECT)
    )
    assert 't1."nom_de_plume" = %s' in sql
    assert "pen_name" not in sql
    assert params == ("Alcott",)


def test_unknown_attribute_still_fails_clearly() -> None:
    """A name that is neither a column nor a relation still raises `AttributeError`."""
    try:
        ProxyBook.author.no_existe  # type: ignore[attr-defined]
    except AttributeError as error:
        assert "no_existe" in str(error)
    else:  # pragma: no cover - it must raise
        raise AssertionError("an AttributeError was expected")
