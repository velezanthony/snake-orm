"""`path_of(proxy)` reads the path a `SnakePathProxy` accumulated, as a FUNCTION and not an attribute.

`SnakeExpr` and `SnakeCollection` both answer `.path`, and a to-one proxy is the one navigation node
that cannot: its `__getattr__` IS the model's namespace, so every public attribute added to it would
shadow a column of the same name. A model with a column called `path` would stop being reachable
through `Post.author.path` the day the proxy grew one.

So the question is asked from outside. It is public rather than a reach into `_path` from another
package, which is the shape a helper takes right before it becomes public by accident — this
repository has the note about `_registry_of` for exactly that.
"""

from __future__ import annotations

import pytest

from snakeorm import SnakeColumn, snake_auto, snake_model, snake_str
from snakeorm.fields import SnakeToOne, path_of, snake_int, snake_to_one
from snakeorm.linker.linker import snake_link
from snakeorm.registry import SnakeRegistry

REG = SnakeRegistry()


@snake_model(table="proxy_path_countries", registry=REG)
class Country:
    """The far end."""

    id: SnakeColumn[int] = snake_auto()
    path: SnakeColumn[str] = snake_str(max_length=40)


@snake_model(table="proxy_path_authors", registry=REG)
class Author:
    """The middle."""

    id: SnakeColumn[int] = snake_auto()
    country_id: SnakeColumn[int] = snake_int()
    country: SnakeToOne[Country] = snake_to_one(country_id)


@snake_model(table="proxy_path_posts", registry=REG)
class Post:
    """The root."""

    id: SnakeColumn[int] = snake_auto()
    author_id: SnakeColumn[int] = snake_int()
    author: SnakeToOne[Author] = snake_to_one(author_id)


snake_link(REG)


def test_a_one_hop_proxy_knows_its_path() -> None:
    """`Post.author` carries `('author',)`."""
    assert path_of(Post.author) == ("author",)


def test_a_two_hop_proxy_accumulates() -> None:
    """`Post.author.country` carries both hops, in order."""
    assert path_of(Post.author.country) == ("author", "country")


def test_a_column_called_path_is_still_reachable() -> None:
    """THE reason this is a function. `Country.path` is a real column and must win.

    Had the proxy grown a `path` property, `Post.author.country.path` would return the proxy's own
    tuple instead of the column expression — a model silently losing a field to the ORM's plumbing,
    with no error anywhere.
    """
    expression = Post.author.country.path

    assert expression.path == ("author", "country", "path")


def test_anything_that_is_not_a_proxy_is_refused() -> None:
    """It takes proxies, and says so rather than returning something plausible."""
    with pytest.raises(TypeError, match="SnakePathProxy"):
        path_of(Post.id)  # type: ignore[arg-type]
