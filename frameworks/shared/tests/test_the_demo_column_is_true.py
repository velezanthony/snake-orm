"""The roadmap's *demo* column says what the demos reach, and this is what makes that true.

A column kept by hand is a fifth place to forget, and this table already has four. So the column is
COMPUTED from the demos —`demo_column.tier_of` walks the call graph from every route and module— and
the assertion below is that the published table equals what the walk finds.

Both directions matter and the file tests both: a cell that claims more than the demos reach is a
lie to a reader, and a cell that claims less sends somebody to write work that already exists.

"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import pkgutil
import re

import pytest

import snakeorm

from shared.tests.demo_column import symbols_of, tier_of

_ROADMAP = pathlib.Path(__file__).resolve().parents[3] / "docs/features.md"
_SPANISH = pathlib.Path(__file__).resolve().parents[3] / "docs/features.es.md"

_HEADERS = frozenset({"feature", "funcionalidad"})
_LEGEND = frozenset({"the name", "el nombre"})


def _feature_rows(page: pathlib.Path) -> list[tuple[str, str]]:
    """`(row name, published demo tier)` for every feature row of the table."""
    found: list[tuple[str, str]] = []
    for line in page.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 5:
            continue
        if (
            cells[0].lower() in _HEADERS
            or cells[0].startswith("**")
            or cells[0] in _LEGEND
        ):
            continue
        name = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cells[0])
        found.append((name, cells[4].strip("`").strip()))
    return found


def test_the_table_is_still_being_read() -> None:
    """The trap of every check that discovers its own input: over an empty parse, nothing fails.

    A count and not a floor, because a floor set under the real number tolerates the difference in
    silence — the lesson `test_limits_are_true` writes down about its own `>= 50`.
    """
    rows = _feature_rows(_ROADMAP)

    assert len(rows) == 84, f"the parse found {len(rows)} feature rows"
    assert any(name.startswith("`filter()`") for name, _ in rows)


@pytest.mark.parametrize(
    "row,published", _feature_rows(_ROADMAP), ids=lambda value: str(value)[:48]
)
def test_every_cell_matches_what_the_demos_reach(row: str, published: str) -> None:
    """One case per row, so a failure names the feature instead of handing back a diff to read."""
    assert published == tier_of(row), (
        f"the roadmap publishes `{published}` for {row!r} and the demos reach `{tier_of(row)}`"
    )


def test_the_two_languages_publish_the_same_demo_column() -> None:
    """The Spanish page carries the same tiers, lined up by ORDER.

    Only the English one is checked against the walk above, so a cell that grew on `.es.md` alone
    would be published to half the readers with nothing computing it. The rows are paired by
    position because their NAMES are the part that is genuinely translated.

    The roadmap is translated while the plans beside it are not, and this test is part of why: it is
    the LIST of what is built, read by somebody deciding whether the ORM does what they need. The
    plans are for whoever builds the next thing, and that reader is already here.
    """
    english = [tier for _, tier in _feature_rows(_ROADMAP)]
    spanish = [tier for _, tier in _feature_rows(_SPANISH)]

    assert english == spanish, "the two roadmaps disagree about what the demos reach"


def test_no_row_is_measured_by_a_symbol_nobody_declared() -> None:
    """Every row either carries its symbol in backticks or is DECLARED, with no third state.

    A row whose symbol was guessed measures the wrong thing quietly, which is worse than a `-`: the
    cell would be answering about a name that means nothing here.
    """
    unmeasurable = [
        name
        for name, _ in _feature_rows(_ROADMAP)
        if symbols_of(name) is None and tier_of(name) != "-"
    ]

    assert unmeasurable == [], (
        f"these rows report a tier with no symbol behind it: {unmeasurable}"
    )


def _every_name_there_is() -> frozenset[str]:
    """Every name the ORM defines plus every name the demo layer defines.

    The universe a symbol can honestly belong to. A symbol outside it names NOTHING — it cannot
    appear in the reachable set for the same reason it cannot appear in a traceback.
    """
    found: set[str] = set()
    for module in pkgutil.walk_packages(snakeorm.__path__, "snakeorm."):
        try:
            loaded = importlib.import_module(module.name)
        except (
            Exception
        ):  # pragma: no cover - an unimportable module is another test's failure
            continue
        for name, value in vars(loaded).items():
            found.add(name)
            if inspect.isclass(value):
                found |= set(vars(value))
    for path in pathlib.Path(__file__).resolve().parents[2].rglob("*.py"):
        if "__pycache__" in path.parts or ".venv" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        found |= {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        }
    return frozenset(found)


_NAMES = _every_name_there_is()


@pytest.mark.parametrize(
    "row",
    [name for name, _ in _feature_rows(_ROADMAP)],
    ids=lambda value: str(value)[:48],
)
def test_every_symbol_names_something_real(row: str) -> None:
    """A declared symbol has to EXIST, and nothing was checking that.

    `test_no_row_is_measured_by_a_symbol_nobody_declared` asks whether somebody wrote the symbol
    down. It cannot ask whether the symbol is a real name, and those are different questions with a
    gap between them that a whole row can fall into: `scalar_subquery` was declared for the
    correlated-subquery row and the ORM has never defined it —the API is `as_scalar`— so that cell
    reported `-` and would have reported `-` for ever, whatever any demo did.

    That is the failure that wastes somebody's afternoon: you build the page, the tier does not
    move, and the code looks wrong because the measurement is. Six symbols across four rows were in
    that state when this was written, and one row read `***` only because a third symbol in its list
    happened to be real.
    """
    unknown = [name for name in (symbols_of(row) or ()) if name not in _NAMES]

    assert not unknown, (
        f"{row!r} is measured by names nothing defines: {unknown}. "
        "Either the API is spelled differently or the row cannot be measured — say which."
    )
