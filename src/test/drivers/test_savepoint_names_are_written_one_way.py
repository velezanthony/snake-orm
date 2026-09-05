"""`SAVEPOINT "x"` is GRAMMAR, so it is written once and the four drivers share it.

There were four `_quote_savepoint`, and they did not agree on what a savepoint name IS:

    psycopg (sync)   escaped the quotes and carried on
    psycopg (async)  validated and raised
    sqlite           validated and raised
    pymysql          escaped, with backticks

The same engine behaved differently in the two colours, on the same grammar. Nothing was reachable
from the public API —`SnakeSession.savepoint` generates the name itself, `f"sp{depth}"`— so this was
never a hole; it was the parity of the seam broken right underneath the test that watches it.

The unified rule VALIDATES and refuses. Escaping is the wrong answer here precisely because the name
is always generated: anything that is not a plain identifier is a bug in whoever called, and
escaping a bug is how it gets written into the database instead of reported.

WHAT IS *NOT* SHARED is the quoting character, and this file says so because getting it wrong is
exactly what happened: a first version of this collapsed the four copies into one that always wrote
`"`, and MySQL answered `ERROR 1064` — it rejects a double-quoted identifier unless `ANSI_QUOTES` is
on. Three integration tests caught it and the unit test here did not, because it only asked about
one character. The rule is shared; the grammar is the engine's.

It is a DRIVER concern and not a Dialect one, which is the other thing this file pins: a driver has
no dialect and never has had — `TimeoutDriver` receives one as a call argument for exactly that
reason.
"""

from __future__ import annotations

import ast
import pathlib
import pkgutil

import pytest

from snakeorm.drivers.savepoints import quote_savepoint

_PACKAGE = pathlib.Path(__file__).resolve().parents[2] / "snakeorm" / "drivers"


@pytest.mark.parametrize("name", ["sp1", "sp42", "_inner", "a_b_9"])
@pytest.mark.parametrize("quote", ['"', "`"])
def test_a_generated_name_is_quoted(name: str, quote: str) -> None:
    """What the session produces goes through untouched, inside the ENGINE's own quote."""
    assert quote_savepoint(name, quote=quote) == f"{quote}{name}{quote}"


def test_each_driver_asks_for_the_character_its_engine_accepts() -> None:
    """MySQL gets a backtick and the other three a double quote. Read from the drivers themselves.

    The pairing is the half a shared helper cannot enforce on its own, and it is the half that broke:
    `SAVEPOINT "sp1"` is `ERROR 1064` on MySQL/MariaDB. Asserted over the source rather than by
    calling, because the character is fixed at each call site and there is nothing to call.
    """
    quotes = {
        module: '"`"' if '"`"' in (_PACKAGE / f"{module}.py").read_text() else "'\"'"
        for module in ("psycopg", "asyncpsycopg", "sqlite", "pymysql")
    }

    assert quotes["pymysql"] == '"`"', (
        "MySQL was handed a double quote: that is ERROR 1064"
    )
    assert quotes["psycopg"] != '"`"'
    assert quotes["asyncpsycopg"] != '"`"'
    assert quotes["sqlite"] != '"`"'


@pytest.mark.parametrize(
    "name", ['a"b', "a b", "", "1sp", "sp;DROP", "señal", "a-b", "a`b"]
)
def test_anything_that_is_not_a_plain_identifier_is_refused(name: str) -> None:
    """Refused, not escaped. The name is generated, so a strange one is a caller's bug.

    Stricter than the `isalnum()` two of the four used, and deliberately: a name starting with a
    digit and a non-ASCII one are both legal under that check and neither is something this ORM
    ever produces.
    """
    with pytest.raises(ValueError, match="savepoint"):
        quote_savepoint(name, quote='"')


def test_no_driver_keeps_a_private_copy_of_this() -> None:
    """Walks the PACKAGE, not a list of four modules.

    A tuple of the four names would go stale the day a fifth driver arrives with its fifth copy —
    and it would go stale quietly, which is the failure this test exists to prevent. `pkgutil` asks
    the directory instead.
    """
    offenders = []
    for module in pkgutil.iter_modules([str(_PACKAGE)]):
        if module.name == "savepoints":
            continue  # the one place it is SUPPOSED to live
        source = (_PACKAGE / f"{module.name}.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and "savepoint" in node.name
                and "quote" in node.name
            ):
                offenders.append(f"{module.name}.{node.name}")

    assert offenders == [], (
        f"these drivers still write the savepoint grammar themselves: {offenders}. It is one rule; "
        f"four copies is how the two colours of one engine came to disagree."
    )
