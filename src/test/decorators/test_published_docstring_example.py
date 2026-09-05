"""The example inside `snake_model.__doc__` is PUBLISHED code, so it is run and its output pinned.

`docs/users/reference/api/models.md` carries a single line — `::: snakeorm.decorators.snake_model` —
and mkdocstrings fills the page from this docstring on every build. Nothing is copied into the `.md`,
which is why searching the docs for the example's names finds nothing: the docstring IS the published
page, and whatever it says goes out in the English reference exactly as written.

It said `@snake_model(table="animales")`, with a `tipo` discriminator and a `raza` column. An
identifier inside an example is CODE, not prose — the reader copies it — and this repository's code
speaks one language.

The example is EXECUTED here rather than compared as text, and what is asserted is what compiling it
produces: the table name, the columns, the shared table. Those are equalities over real metadata, not
a judgement about words — the only kind of check this repository trusts since `test_strings_are_english`
was deleted for promising more than it could deliver.
"""

from __future__ import annotations

import importlib.util
import re
import textwrap
import sys
from pathlib import Path
from types import ModuleType

import pytest

from snakeorm.decorators import snake_model, snake_table

_BLOCK = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _published_example() -> str:
    """The python block of the docstring that mkdocstrings publishes."""
    doc = snake_model.__doc__
    assert doc is not None, (
        "snake_model has no docstring, so the reference page would be empty"
    )
    blocks = _BLOCK.findall(doc)
    assert len(blocks) == 1, f"expected ONE published example, found {len(blocks)}"
    # 3.13 strips the docstring's common indentation when it compiles it; 3.11 and 3.12 do not, and
    # the example does not compile with it.
    return textwrap.dedent(str(blocks[0]))


def _scoped(source: str) -> str:
    """Send the example's models to a registry of their own.

    The global registry rightly refuses two models on one table, and this file is not entitled to
    reserve the example's table name for the whole test session. The trick is the one
    `test_scaffold_e2e` already uses; it changes where the models register, not what they declare.
    """
    return (
        "from snakeorm import *\n"
        "from snakeorm.registry import SnakeRegistry\n"
        "scoped = SnakeRegistry()\n"
        + source.replace("@snake_model(", "@snake_model(registry=scoped, ")
    )


@pytest.fixture(scope="module")
def example(tmp_path_factory: pytest.TempPathFactory) -> ModuleType:
    """The published example, written to a file and IMPORTED like any user's models module.

    A file and not an `exec` into a dictionary: the compiler resolves the annotations against the
    model's MODULE globals, and a loose namespace is not a module. Importing it for real also proves
    the thing that matters most about a published example — that it works as written.
    """
    path = Path(str(tmp_path_factory.mktemp("published"))) / "published_example.py"
    path.write_text(_scoped(_published_example()))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def test_the_published_example_runs(example: ModuleType) -> None:
    """The example in the reference page imports and compiles: a reader can paste it and it works."""
    assert isinstance(example.Animal, type)
    assert isinstance(example.Dog, type)


def test_the_published_example_declares_the_table_it_names(example: ModuleType) -> None:
    """The `table=` of the example reaches the compiled metadata as written."""
    assert snake_table(example.Animal, example.scoped).name == "animals"


def test_the_published_example_names_its_columns_in_one_language(
    example: ModuleType,
) -> None:
    """The discriminator and the child's column carry the names the example shows.

    They were `tipo` and `raza`. The assertion is on the COMPILED column names and not on the
    docstring's text: what a reader copies is the code, so the code is what gets checked.
    """
    assert {
        column.name for column in snake_table(example.Animal, example.scoped).columns
    } == {
        "id",
        "kind",
    }
    assert "breed" in {
        column.name for column in snake_table(example.Dog, example.scoped).columns
    }


def test_the_polymorphic_child_of_the_example_shares_the_base_table(
    example: ModuleType,
) -> None:
    """The example's whole point holds: the child picks no table, it shares the base's.

    Without this the block would be prose that happens to parse; with it, the sentence right above it
    —"they do not pick a table, because there is none to pick"— is verified rather than promised.
    """
    assert (
        snake_table(example.Dog, example.scoped).name
        == snake_table(example.Animal, example.scoped).name
    )
