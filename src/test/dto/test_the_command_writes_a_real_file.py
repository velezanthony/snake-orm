"""`snakeorm dto` end to end: a real file on disk, read, rewritten, and imported back.

Everything above this file works on strings, which is the right way to test a splice and the wrong
way to believe it. The last net runs the command the way a person does — a file path, `--sync`
writing to disk — and then IMPORTS the result, because a generator whose output is only ever
compared as text is a generator that can emit a file nobody can load.

Two exit codes, and they are the product: without `--sync` the command REPORTS and fails, which is
what turns a DTO that stopped matching its model into a red build instead of a wrong response
nobody looked at.

The unit is a FILE and not a module, and that is the point of the whole design: the specs are read
out of the source with `ast`, so the command never imports what it is about to rewrite. Only the
MODELS module is imported, because the compiled metadata is what has the types.
"""

from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys
from collections.abc import Iterator

import pytest

from snakeorm.cli.app import main
from snakeorm.registry import registry

_MODELS = '''"""The models the DTOs of this package describe."""

from __future__ import annotations

from snakeorm import SnakeColumn, snake_auto, snake_model, snake_str
from snakeorm.fields import SnakeToOne, snake_int, snake_to_one
from snakeorm.linker.linker import snake_link


@snake_model(table="dtocli_authors")
class Author:
    """An author."""

    id: SnakeColumn[int] = snake_auto()
    username: SnakeColumn[str] = snake_str(max_length=50)


@snake_model(table="dtocli_posts")
class Post:
    """A post with a required author and an optional editor."""

    id: SnakeColumn[int] = snake_auto()
    title: SnakeColumn[str] = snake_str(max_length=200)
    secret: SnakeColumn[str] = snake_str(max_length=200)
    author_id: SnakeColumn[int] = snake_int()
    editor_id: SnakeColumn[int | None] = snake_int()
    author: SnakeToOne[Author] = snake_to_one(author_id)
    editor: SnakeToOne[Author | None] = snake_to_one(editor_id)


snake_link()
'''

_DTOS = '''"""What the feed hands out."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from dtocli.models import Author, Post
    from snakeorm.dto import snake_dto

    # Everything in here goes over the wire on every page load.
    snake_dto(Author, fields=[Author.id, Author.username], name="AuthorDto")
    snake_dto(
        Post,
        fields=[Post.id, Post.title, Post.author, Post.editor],
        name="PostCard",
    )
'''


_REGISTRY_INDEXES = ("_tables", "_by_name", "_model_by_name", "_table_owner")
"""The four dicts `@snake_model` writes into. Snapshotted and put back around this module.

Restoring them is NOT tidiness. The models here live in a module under `tmp_path`, and dropping that
module from `sys.modules` while its classes stay registered leaves the linker holding a class whose
globals no longer exist: the next `snake_link()` anywhere in the suite dies with
`NameError: name 'SnakeColumn' is not defined`, in a file that has nothing to do with DTOs. Measured
— it took out twenty tests in `test/fields/`.
"""


@pytest.fixture(scope="module")
def package(tmp_path_factory: pytest.TempPathFactory) -> Iterator[pathlib.Path]:
    """A real package on `sys.path` with a models module and a DTO file that has no region yet."""
    root = tmp_path_factory.mktemp("dtocli_root")
    directory = root / "dtocli"
    directory.mkdir()
    (directory / "__init__.py").write_text("", encoding="utf-8")
    (directory / "models.py").write_text(_MODELS, encoding="utf-8")
    snapshot = {name: dict(getattr(registry, name)) for name in _REGISTRY_INDEXES}
    sys.path.insert(0, str(root))
    try:
        yield directory
    finally:
        sys.path.remove(str(root))
        for name, saved in snapshot.items():
            getattr(registry, name).clear()
            getattr(registry, name).update(saved)
        for name in [item for item in sys.modules if item.startswith("dtocli")]:
            del sys.modules[name]


@pytest.fixture
def dtos(package: pathlib.Path) -> pathlib.Path:
    """The DTO file, put back to its spec-only state before each test."""
    path = package / "dto.py"
    path.write_text(_DTOS, encoding="utf-8")
    return path


def test_sync_writes_the_classes_into_the_file(
    dtos: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--sync` appends the region, in dependency order, and says what it wrote."""
    code = main(["dto", "--file", str(dtos), "--sync"])

    written = dtos.read_text(encoding="utf-8")
    assert code == 0
    assert written.startswith(_DTOS)
    assert written.index("class AuthorDto") < written.index("class PostCard")
    assert "    author: AuthorDto\n" in written
    assert "    editor: AuthorDto | None\n" in written
    assert "secret" not in written

    printed = capsys.readouterr().out
    assert "AuthorDto: added `id: int`" in printed
    assert "PostCard: added `editor: AuthorDto | None`" in printed


def test_what_it_wrote_imports_and_is_a_typed_dict(dtos: pathlib.Path) -> None:
    """The rewritten module imports, and the classes carry the generated keys.

    Comparing the text would only prove the text. Importing proves Python accepts the file, and the
    keys a checker will read are the ones the specs asked for.
    """
    main(["dto", "--file", str(dtos), "--sync"])

    module = importlib.import_module("dtocli.dto")

    assert set(module.PostCard.__annotations__) == {"id", "title", "author", "editor"}
    assert set(module.AuthorDto.__annotations__) == {"id", "username"}


def test_importing_the_dto_file_does_not_drag_in_the_models(
    dtos: pathlib.Path, package: pathlib.Path
) -> None:
    """The specs live under `TYPE_CHECKING`, so a view importing the DTOs pays nothing for them.

    Measured in a SUBPROCESS, and it has to be. Asking the question in this process would mean
    emptying `sys.modules` first, which re-executes `@snake_model` and collides in the global
    registry — the test would be measuring its own clean-up. A fresh interpreter measures the
    property itself: import `dtocli.dto`, and `dtocli.models` must not be there afterwards.
    """
    main(["dto", "--file", str(dtos), "--sync"])

    finished = subprocess.run(  # noqa: S603 - fixed command, no user input
        [
            sys.executable,
            "-c",
            "import sys; import dtocli.dto; print('dtocli.models' in sys.modules)",
        ],
        cwd=package.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert finished.returncode == 0, finished.stderr
    assert finished.stdout.strip() == "False"


def test_without_sync_it_reports_and_fails_and_writes_nothing(
    dtos: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default run is a CHECK: exit code 1, the file untouched, the drift named.

    This is the half that makes the tool worth wiring into CI, and it executes nothing of the
    user's: the specs are read, never run.
    """
    code = main(["dto", "--file", str(dtos)])

    assert code == 1
    assert dtos.read_text(encoding="utf-8") == _DTOS
    assert "AuthorDto: added `id: int`" in capsys.readouterr().out


def test_a_second_sync_changes_nothing_and_succeeds(
    dtos: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Run it twice: byte for byte the same file, and no change reported.

    Idempotence is pinned on strings elsewhere; this pins it through the command, the file system
    and the encoding, which is where a stray newline would show up.
    """
    main(["dto", "--file", str(dtos), "--sync"])
    once = dtos.read_bytes()
    capsys.readouterr()

    code = main(["dto", "--file", str(dtos), "--sync"])

    assert code == 0
    assert dtos.read_bytes() == once
    assert "up to date" in capsys.readouterr().out


def test_a_synced_file_passes_the_check(dtos: pathlib.Path) -> None:
    """After `--sync`, the check goes green: the two modes agree about what is right."""
    main(["dto", "--file", str(dtos), "--sync"])

    assert main(["dto", "--file", str(dtos)]) == 0


def test_a_file_with_no_specs_is_reported_not_ignored(
    package: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Pointing the command at a file that declares no DTO is an ERROR, not a quiet success.

    Silence there reads exactly like a clean run, and the likeliest cause is the wrong path. It
    travels through the CLI's one failure channel, which is what the `Error:` prefix pins down.
    """
    code = main(["dto", "--file", str(package / "models.py")])

    printed = capsys.readouterr()
    assert code == 1
    assert printed.err.startswith("Error: ")
    assert "declares no snake_dto" in printed.err
    assert printed.out == ""


def test_a_file_that_does_not_exist_is_reported(
    package: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A mistyped path says so instead of raising something from the file system layer."""
    code = main(["dto", "--file", str(package / "nope.py")])

    assert code == 1
    assert "does not exist" in capsys.readouterr().err
