"""Many-to-many EXECUTED. No server needed: it runs on SQLite in memory.

Emission proves the SQL has a JOIN. Only execution proves what matters: that every parent gets ITS
own children and not the neighbour's, that a parent without links gets an empty list instead of
staying unloaded, and that all of that costs TWO queries.

That count is half the test. Loading an m2m with one query per parent works just as well in the
tests and falls apart with real data.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from snakeorm import (
    SQLiteDialect,
    SQLiteDriver,
    SnakeColumn,
    SnakeModel,
    SnakeQuery,
    SnakeSession,
    SnakeToMany,
    SnakeToOne,
    snake_auto,
    snake_int,
    snake_model,
    snake_str,
    snake_table,
    snake_to_many_through,
    snake_to_one,
)
from snakeorm.linker import snake_link
from snakeorm.migration import emit_create_table

_DIALECT = SQLiteDialect()


@snake_model(table="mm_articles")
class Article(SnakeModel):
    """An article with its tags on the other side of the bridge."""

    id: SnakeColumn[int] = snake_auto()
    titulo: SnakeColumn[str] = snake_str()
    tags: SnakeToMany["Tag"] = snake_to_many_through(
        through="Tag2Article", via="article", to="tag"
    )


@snake_model(table="mm_tags")
class Tag(SnakeModel):
    """A tag, navigable towards its articles as well."""

    id: SnakeColumn[int] = snake_auto()
    name: SnakeColumn[str] = snake_str()
    articles: SnakeToMany[Article] = snake_to_many_through(
        through="Tag2Article", via="tag", to="article"
    )


@snake_model(table="mm_tag_article")
class Tag2Article(SnakeModel):
    """The bridge. An ordinary model — and that is why it can carry columns of its own."""

    id: SnakeColumn[int] = snake_auto()
    article_id: SnakeColumn[int] = snake_int()
    tag_id: SnakeColumn[int] = snake_int()
    article: SnakeToOne[Article] = snake_to_one(article_id)
    tag: SnakeToOne[Tag] = snake_to_one(tag_id)


@pytest.fixture
def environment() -> Iterator[tuple[SnakeSession, list[str]]]:
    """In-memory database with two articles, three tags and a few crossed links."""
    snake_link()
    driver = SQLiteDriver.connect(":memory:")
    for model in (Article, Tag, Tag2Article):
        driver.execute(emit_create_table(snake_table(model), _DIALECT), ())
    driver.commit()

    log: list[str] = []

    class Espia:
        """Driver that writes down the SQL: the query count is part of the test."""

        def __init__(self, inner: SQLiteDriver) -> None:
            self._inner = inner

        def fetch_all(self, sql: str, params: object = ()) -> list[tuple[object, ...]]:
            log.append(sql)
            return self._inner.fetch_all(sql, params)  # type: ignore[arg-type]

        def execute(self, sql: str, params: object = ()) -> int:
            return self._inner.execute(sql, params)  # type: ignore[arg-type]

        def commit(self) -> None:
            self._inner.commit()

        def rollback(self) -> None:
            self._inner.rollback()

    session = SnakeSession(Espia(driver), _DIALECT)  # type: ignore[arg-type]
    python = session.add(Article(titulo="Python"))
    sql_article = session.add(Article(titulo="SQL"))
    session.add(Article(titulo="Suelto"))  # without tags: the case everyone forgets
    tags = [session.add(Tag(name=n)) for n in ("orm", "tipos", "bbdd")]
    session.add_all(
        [
            Tag2Article(article_id=python.id, tag_id=tags[0].id),
            Tag2Article(article_id=python.id, tag_id=tags[1].id),
            Tag2Article(article_id=sql_article.id, tag_id=tags[2].id),
        ]
    )
    session.commit()
    log.clear()
    try:
        yield session, log
    finally:
        driver.close()


def test_each_parent_gets_its_own_children(
    environment: tuple[SnakeSession, list[str]],
) -> None:
    """Every article gets ITS own tags, not the neighbour's.

    It is what the JOIN against the bridge has to get right, and where a badly done grouping would
    give plausible but wrong results — the worst kind of failure.
    """
    session, _ = environment
    articles = session.all(
        SnakeQuery(Article).include(Article.tags).order_by(Article.id.asc())
    )

    by_title = {a.titulo: sorted(t.name for t in a.tags) for a in articles}
    assert by_title == {
        "Python": ["orm", "tipos"],
        "SQL": ["bbdd"],
        "Suelto": [],
    }


def test_a_parent_without_links_gets_an_empty_list(
    environment: tuple[SnakeSession, list[str]],
) -> None:
    """A parent without links gets `[]`, it does not stay UNLOADED.

    The difference matters: unloaded, touching the relation would trip the anti-N+1 latch saying
    it was never asked for — and that would be a lie, because it was asked for and the answer is
    "none".
    """
    session, _ = environment
    loose = session.first(
        SnakeQuery(Article).filter(Article.titulo == "Suelto").include(Article.tags)
    )

    assert loose is not None
    assert loose.tags == []


def test_loading_the_whole_thing_costs_two_queries(
    environment: tuple[SnakeSession, list[str]],
) -> None:
    """Three articles and their tags: TWO queries, not four.

    One for the parents and another for all the children with their link. Without this, an m2m is
    an N+1 with better press.
    """
    session, log = environment
    log.clear()

    session.all(SnakeQuery(Article).include(Article.tags))

    assert len(log) == 2, f"parents + children: dos consultas, fueron {len(log)}"
    assert "JOIN" in log[1], "the second one crosses the bridge"


def test_it_navigates_in_the_other_direction_too(
    environment: tuple[SnakeSession, list[str]],
) -> None:
    """From the tag towards the articles: an m2m has no "main" side."""
    session, _ = environment
    orm = session.first(SnakeQuery(Tag).filter(Tag.name == "orm").include(Tag.articles))

    assert orm is not None
    assert [article.titulo for article in orm.articles] == ["Python"]


def test_linking_is_an_ordinary_insert(
    environment: tuple[SnakeSession, list[str]],
) -> None:
    """Linking is inserting the bridge row with `add()`. The ORM writes nothing you did not ask for.

    Django exposes `post.tags.add(tag)`, which writes to the database when you touch an attribute.
    Here the write is visible: it is a row of a model you declared, with its `add` and its `commit`.
    """
    session, _ = environment
    loose = session.first(SnakeQuery(Article).filter(Article.titulo == "Suelto"))
    tag = session.first(SnakeQuery(Tag).filter(Tag.name == "orm"))
    assert loose is not None and tag is not None

    session.add(Tag2Article(article_id=loose.id, tag_id=tag.id))
    session.commit()

    reloaded = session.first(
        SnakeQuery(Article).filter(Article.id == loose.id).include(Article.tags)
    )
    assert reloaded is not None
    assert [t.name for t in reloaded.tags] == ["orm"]
