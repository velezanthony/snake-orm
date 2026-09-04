"""The React client's shapes say the SAME thing as the payload the demos build.

TWO COMPILERS THAT CANNOT SEE EACH OTHER. `npm run typecheck` runs `tsc` over TypeScript alone and
has never heard of Python; `mypy` and `pyright` read the package and have never heard of
TypeScript. Both come out green over a client reading a field the server does not send, and the only
place that meets is a browser.

The shapes agree today — they were compared by hand, field by field, and they matched. That is
exactly the state this repository distrusts: the same class of agreement the nav catalogue had
before it drifted, and the demo ports had before the Makefile started FastAPI on 8000 while the
client proxied to 8001. Two hand-kept copies of one fact agree until the morning they do not, and
nothing announces the morning.

WHAT IT COMPARES AND WHAT IT DOES NOT. Names and their kinds, per field: a `str` must arrive as a
`string`, an `int` or a `float` as a `number`, a nested Dto as the interface of the same name. It
does NOT check that the value is right — `frameworks/shared/tests/` already drives the endpoints
for that. This answers the one question neither type-checker can: do the two declarations describe
the same JSON.

IT GROWS WITH THE MIGRATION, and that is the point of walking the dicts rather than a written list.
The generated `TypedDict`s are the source, and only `blog_dto.py` has them so far; the day another
module is migrated its shapes join this comparison without anybody remembering to add them. A list
written here would be the fourth hand-kept copy, which is the defect the file exists to prevent.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
_DTO = _REPO / "frameworks" / "shared" / "dto"
_CLIENT = _REPO / "frameworks" / "react_front" / "src" / "domains"

_KINDS = {
    "int": "number",
    "float": "number",
    "str": "string",
    "bool": "boolean",
}
"""How a Python annotation reaches JSON, and what TypeScript calls it there.

`Decimal` and `datetime` are deliberately absent: both cross as strings today, but which one a
column becomes is the coercion layer's business and not this file's, and guessing here would pin a
decision that lives elsewhere. A field annotated with either is reported as unmapped rather than
assumed — an unknown that says so beats a mapping that quietly agrees.
"""


def _typed_dicts() -> dict[str, dict[str, str]]:
    """Every generated `TypedDict` in `shared/dto/`, as `{name: {field: annotation}}`.

    Read with `ast` and never imported. Importing would pull the whole demo domain —models, engine,
    a live connection— into a test whose entire question is textual, and it would fail for reasons
    that have nothing to do with the shapes.
    """
    found: dict[str, dict[str, str]] = {}
    for module in sorted(_DTO.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                isinstance(base, ast.Name) and base.id == "TypedDict"
                for base in node.bases
            ):
                continue
            fields = {
                statement.target.id: ast.unparse(statement.annotation)
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
            }
            found[node.name] = fields
    return found


_INTERFACE = re.compile(r"^export interface (\w+) \{(.*?)^\}", re.M | re.S)
_FIELD = re.compile(r"^\s{2}(\w+)(\??):\s*([^;]+);", re.M)


def _interfaces() -> dict[str, dict[str, tuple[str, bool]]]:
    """Every client interface, as `{name: {field: (type, optional)}}`.

    A regex and not a TypeScript parser, and the shape of the client is what allows it: these files
    are flat records of primitives and other interfaces, written by hand in one style. The floor
    below refuses to let that assumption rot silently — the day somebody writes a union or a generic
    the count stops matching and this file says so instead of skipping the field.
    """
    found: dict[str, dict[str, tuple[str, bool]]] = {}
    for module in sorted(_CLIENT.rglob("types.ts")):
        text = module.read_text(encoding="utf-8")
        for name, body in _INTERFACE.findall(text):
            found[name] = {
                field: (kind.strip(), optional == "?")
                for field, optional, kind in _FIELD.findall(body)
            }
    return found


def _paired() -> list[tuple[str, str]]:
    """`(dict name, interface name)` for every generated shape the client also declares.

    `PostDto` pairs with `Post`, `UserDto` with `User`. A dict with no interface is not a failure:
    the server may build a payload no client reads yet, and demanding one would be inventing work.
    What is a failure is the two disagreeing, which is what the tests below are for.
    """
    interfaces = _interfaces()
    pairs = []
    for dict_name in _typed_dicts():
        bare = dict_name.removesuffix("Dto")
        if bare in interfaces:
            pairs.append((dict_name, bare))
    return pairs


def test_both_sides_were_actually_read() -> None:
    """The floor, and it is not ceremony: every test below is a loop over what these two return.

    A regex that stopped matching —a formatter reflowing the interfaces, a `types.ts` moving— would
    empty one side, and "no pair disagrees" holds perfectly over no pairs. This is what refuses to
    let the comparison pass by finding nothing.
    """
    dicts, interfaces, pairs = _typed_dicts(), _interfaces(), _paired()

    assert dicts, "no generated TypedDict was read out of shared/dto/"
    assert len(interfaces) > 20, f"only {len(interfaces)} client interfaces were parsed"
    assert pairs, "no generated shape pairs with a client interface"
    assert all(fields for fields in interfaces.values()), (
        "an interface parsed with NO fields, which means the field regex stopped matching: "
        + ", ".join(name for name, fields in interfaces.items() if not fields)
    )


def test_every_client_module_yielded_an_interface() -> None:
    """Each `types.ts` has to produce at least one interface, and this was learned the hard way.

    The floor above is a TOTAL —"more than twenty were parsed"— and a total hides a single loss. It
    was proved by hand: reformatting one line of the blog's `types.ts` so the header regex missed it
    dropped `Post` out of the pairing, the parametrised comparisons for it silently stopped
    existing, and the file still reported everything green. That is the vacuous pass this repository
    keeps finding, produced by its own net.

    Per module, a loss has nowhere to hide: the file that stopped parsing is the file that is named.
    """
    parsed = {
        module: _INTERFACE.findall(module.read_text(encoding="utf-8"))
        for module in sorted(_CLIENT.rglob("types.ts"))
    }

    assert parsed, "no `types.ts` was found under the client's domains"
    empty = [
        str(module.relative_to(_REPO)) for module, found in parsed.items() if not found
    ]
    assert empty == [], (
        "these client modules parsed to NO interface, so whatever they declare is being compared "
        "against nothing:\n  " + "\n  ".join(empty)
    )


@pytest.mark.parametrize("dict_name,interface", _paired())
def test_the_client_declares_every_field_the_payload_sends(
    dict_name: str, interface: str
) -> None:
    """A field the server sends and the client does not declare is a field the client cannot read.

    Not cosmetic: the client's `DataTable` renders by column key, so a payload that grew a field
    silently is work already done on the server and invisible in the browser.
    """
    sent = set(_typed_dicts()[dict_name])
    declared = set(_interfaces()[interface])

    assert sent <= declared, (
        f"{dict_name} sends {sorted(sent - declared)}, which `{interface}` does not declare. "
        f"Either the client grows the field or the payload stops building it."
    )


@pytest.mark.parametrize("dict_name,interface", _paired())
def test_the_client_invents_no_field_the_payload_never_sends(
    dict_name: str, interface: str
) -> None:
    """A REQUIRED field the client declares and the server never sends arrives as `undefined`.

    Optional ones are exempt and that is the whole distinction: `author?: User` is how the client
    says "this comes only when the query included it", which is exactly what `PostDto` versus
    `PostWithAuthorDto` says on the other side. A field marked optional is a declared maybe; one
    without the mark is a promise, and an unkept promise renders as blank and blames the data.
    """
    sent = set(_typed_dicts()[dict_name])
    required = {
        field
        for field, (_kind, optional) in _interfaces()[interface].items()
        if not optional
    }

    assert required <= sent, (
        f"`{interface}` requires {sorted(required - sent)}, which {dict_name} never sends. "
        f"Mark them optional if a wider payload carries them, or build them."
    )


@pytest.mark.parametrize("dict_name,interface", _paired())
def test_a_field_means_the_same_thing_on_both_sides(
    dict_name: str, interface: str
) -> None:
    """Agreeing on the NAMES and disagreeing on the kinds is the worse half of the same bug.

    A `visit_count: string` on the client typechecks, renders, and sorts a table alphabetically —
    `10` before `9` — with nothing red anywhere. Names are the easy half; this is the half that
    reaches somebody looking at a board.
    """
    fields = _typed_dicts()[dict_name]
    declared = _interfaces()[interface]

    wrong = []
    for field, annotation in fields.items():
        if field not in declared:
            continue  # the test above owns this one
        expected = _KINDS.get(annotation) or annotation.removesuffix("Dto")
        actual = declared[field][0]
        if actual != expected:
            wrong.append(f"{field}: server says {annotation!r}, client says {actual!r}")

    assert wrong == [], f"{dict_name} and `{interface}` disagree:\n  " + "\n  ".join(
        wrong
    )
