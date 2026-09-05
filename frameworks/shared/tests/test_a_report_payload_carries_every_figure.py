"""A report's JSON payload carries every figure the report is MADE of, one key per field.

THE FAILURE THIS EXISTS FOR WAS FOUND, NOT IMAGINED. `OrderReport` has six fields and
`order_report_dict` named five of them: `baskets` — the table both SSR demos render, the one figure
on that report that is a folded LIST rather than a number — never reached `/api/orders/report` at
all. The docstring above the serialiser said "five reads, five keys" and it was internally
consistent, which is what let it stand: the payload was well formed, every key in it was correct,
and the only thing wrong with it was a figure that was not there.

WHY NO OTHER NET COULD SEE IT, and this is the part worth keeping. The page and the endpoint reach
the SAME use case, so `test_the_page_and_the_api_reach_one_usecase.py` compares one operation on two
surfaces and correctly reports no divergence — the seam it guards was intact. The route comparison in
`test_the_demos_serve_the_same_routes.py` sees two routes that both exist, on all three demos.
`test_reports.py` pins the statement BUDGET, so the query still ran and still cost what it cost; the
figure was fetched from the database and then dropped on the floor one layer above.

That layer is `shared/dto/`, and it is the one layer the BFF is ALLOWED to differ in — `viewmodels`
for HTML, `dto` for JSON, which is the whole design. A figure can only go missing here, precisely
because here is where the two presentations part company, so here is where somebody has to count.

HOW IT COUNTS: by READING, never by calling. The serialisers are found by name in the source, the
dataclass each one takes is resolved from its annotation, and the keys are read off the `return`
statement's dict literal with `ast`. Nothing is executed and nothing is fixtured, which means this
net costs no seeding and cannot be made to pass by a report that happens to be empty on the day it
runs — the two ways a check like this usually goes quietly green.

AND IT REFUSES TO SKIP. A serialiser it cannot read — one that builds its dict with a comprehension,
or returns a name — is a FAILURE naming the function, not a silent pass. A net that covers less than
it appears to is the shape of failure this repository has deleted files over.

WHAT IS DELIBERATELY NOT ASSERTED is the other direction. A payload is free to carry MORE than the
dataclass has: a derived figure, a flag about the engine. What it is not free to do is carry less,
because less is a question the HTML answers and the JSON does not, inside one application that
claims to be the same decision in two formats.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import pathlib
import typing

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DTO = _ROOT / "shared/dto"

# What a report serialiser is called. The convention is already universal in this package —
# `order_report_dict`, and every report DTO written since — so the suffix is a discovery rule rather
# than a list somebody has to remember to extend. A report DTO named some other way is invisible
# here, which is the honest cost of discovering by name and the reason the name is a convention.
_SUFFIX = "_report_dict"


def _serialisers() -> list[tuple[str, str]]:
    """Every `(module, function)` in `shared/dto/` that serialises a report, found in the source."""
    found: list[tuple[str, str]] = []
    for path in sorted(_DTO.glob("*_dto.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.endswith(_SUFFIX):
                found.append((f"shared.dto.{path.stem}", node.name))
    return found


def _returned_keys(module: str, function: str) -> list[str] | None:
    """The literal string keys of the dict a serialiser returns, or None if it cannot be read.

    None and not an empty list, because the two mean opposite things: a serialiser that returns a
    dict with no keys is a bug this net should report, and one built in a way this reader does not
    understand is a bug in the READER. Collapsing them would let the second look like the first.
    """
    path = _DTO / (module.rpartition(".")[2] + ".py")
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if not (isinstance(node, ast.FunctionDef) and node.name == function):
            continue
        for statement in ast.walk(node):
            if not isinstance(statement, ast.Return):
                continue
            if not isinstance(statement.value, ast.Dict):
                return None
            keys: list[str] = []
            for key in statement.value.keys:
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    return None
                keys.append(key.value)
            return keys
    return None


def _report_class(module: str, function: str) -> type | None:
    """The dataclass a serialiser takes, resolved from its annotation. None if it takes something else."""
    imported = importlib.import_module(module)
    hints = typing.get_type_hints(getattr(imported, function))
    hints.pop("return", None)
    candidates = [
        value
        for value in hints.values()
        if isinstance(value, type) and dataclasses.is_dataclass(value)
    ]
    return candidates[0] if len(candidates) == 1 else None


_SERIALISERS = _serialisers()


def test_there_are_report_serialisers_to_check() -> None:
    """The discovery found something, which is the trap of every self-discovering net.

    With an empty list every parametrised case below vanishes and the suite reports that the reports
    are whole when it has not looked at one. It is the same vacuous-run guard `test_async_mirror.py`
    and `test_the_demos_serve_the_same_routes.py` open with, and for the same reason: the failure
    mode of a reader is silence, not noise.
    """
    assert _SERIALISERS, (
        f"no `*{_SUFFIX}` found under {_DTO}: either the reports lost their JSON side or the naming "
        f"convention moved, and this file is now checking nothing."
    )


@pytest.mark.parametrize(("module", "function"), _SERIALISERS)
def test_a_report_serialiser_can_be_read(module: str, function: str) -> None:
    """Each serialiser returns a dict literal with constant keys, so its payload can be counted.

    Declared as its own case rather than folded into the one below, because "the figure is missing"
    and "the reader cannot tell" are different findings with different fixes, and a net that reports
    the second as the first sends somebody to the wrong file.
    """
    keys = _returned_keys(module, function)

    assert keys is not None, (
        f"{module}.{function} does not return a dict of literal keys, so what it publishes cannot "
        f"be counted against the report it takes. Either give it a literal dict — which is what "
        f"every DTO in this package is, and what makes a missing figure visible in a diff — or "
        f"teach this reader the new shape. Skipping it quietly is the one thing that is not allowed."
    )
    assert keys, f"{module}.{function} publishes nothing at all."


@pytest.mark.parametrize(("module", "function"), _SERIALISERS)
def test_every_figure_of_a_report_reaches_its_payload(
    module: str, function: str
) -> None:
    """Every field of the report dataclass is a key of the payload the serialiser returns.

    The dataclass is the report: its docstring in `shared/usecases/` says the figures travel together
    because they are read together and because a caller that fetches them separately is the caller
    that forgets one. The payload is that same answer in JSON, so a field with no key is the figure
    the HTML shows and the JSON does not — which is the BFF being two implementations in the only
    layer where it is allowed to be two presentations.
    """
    report = _report_class(module, function)
    assert report is not None, (
        f"{module}.{function} does not take exactly one dataclass, so there is nothing to count its "
        f"payload against."
    )
    keys = _returned_keys(module, function)
    assert keys is not None
    missing = sorted(
        field.name for field in dataclasses.fields(report) if field.name not in keys
    )

    assert missing == [], (
        f"{report.__name__} carries {missing} and {module}.{function} does not publish them. The "
        f"query ran and paid for them — the statement budget in `test_reports.py` still counts it — "
        f"and they were dropped on the way out. Add a key per figure, or take the field off the "
        f"report if nothing wants it."
    )
