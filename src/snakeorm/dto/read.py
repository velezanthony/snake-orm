"""Reading the declarations out of a DTO file with `ast`, without importing or running it.

The declarations live under `if TYPE_CHECKING:`, so there is nothing to run: the interpreter never
reaches them and only a checker looks. That is not an obstacle this module works around, it is the
arrangement that makes the whole thing safe — a tool that rewrites your file does not execute your
file, and the check mode in particular touches nothing of yours at all.

The ONLY thing imported is the models module the file names, because the compiled metadata is where
the types, the nullability and the relationships live. The AST gives names; `SnakeTableInfo` gives
the truth.

Reading also sees something evaluating cannot. The source says which name a path is ROOTED at, and
the evaluated descriptor has forgotten: `Post.author.username` and `Author.username` both come out
as a `SnakeExpr` that knows its own steps and not whose they are. So a spec over `Post` that selects
`Author.id` — which type-checks, because `Author.id` is a perfectly good expression — is a refusal
here and was invisible before.
"""

from __future__ import annotations

import ast
import importlib

from snakeorm.core.exceptions import SnakeDtoError
from snakeorm.dto.spec import SnakeDtoPick, SnakeDtoSpec, build_spec

_SNAKE_DTO = "snakeorm.dto.snake_dto"
"""The dotted path the declaration function is imported from.

Matched through the file's IMPORTS rather than by the literal text `snake_dto`, so an alias reads
and somebody else's function of the same name does not.
"""


def specs_in_source(source: str, *, path: str = "<source>") -> tuple[SnakeDtoSpec, ...]:
    """Every `snake_dto(...)` declaration in this source, in the order it was written.

    Model modules are imported as they are named — that is what compiles the metadata — but the file
    being read never is.
    """
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        raise SnakeDtoError(
            f"{path} is not valid Python, so there are no declarations to read: {error}"
        ) from error
    statements = _reachable(tree)
    imports = _imported_paths(statements)
    callers = {local for local, dotted in imports.items() if dotted == _SNAKE_DTO}
    return tuple(
        _spec_of(call, imports, path)
        for statement in statements
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and _called_name(statement.value) in callers
        for call in [statement.value]
    )


def _reachable(tree: ast.Module) -> list[ast.stmt]:
    """The module's own statements, plus the bodies of its `if TYPE_CHECKING:` blocks.

    Both spellings of the guard count, the bare name and the attribute. Recognising only one would
    reject a file that is correct, which is the same fail-in-the-open shape as identifying a
    TypedDict by the text of its base class.
    """
    statements: list[ast.stmt] = []
    for statement in tree.body:
        if isinstance(statement, ast.If) and _is_type_checking(statement.test):
            statements.extend(statement.body)
        else:
            statements.append(statement)
    return statements


def _is_type_checking(test: ast.expr) -> bool:
    """Whether an `if` guards a type-checking-only block, written either way round."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _imported_paths(statements: list[ast.stmt]) -> dict[str, str]:
    """Every name the file binds by importing, mapped to the dotted path it came from.

    Only `from x import Y`, because that is what binds a CLASS. A plain `import x.y` binds a module,
    and a module is neither a model nor the declaration function. A relative import is left out: it
    gives no absolute path to import back, and guessing the package from the file would be guessing.
    """
    paths: dict[str, str] = {}
    for statement in statements:
        if not isinstance(statement, ast.ImportFrom) or statement.module is None:
            continue
        if statement.level:
            continue
        for alias in statement.names:
            paths[alias.asname or alias.name] = f"{statement.module}.{alias.name}"
    return paths


def _called_name(call: ast.Call) -> str:
    """The bare name a call is made through, or `""` for anything more complicated."""
    return call.func.id if isinstance(call.func, ast.Name) else ""


def _spec_of(call: ast.Call, imports: dict[str, str], path: str) -> SnakeDtoSpec:
    """One `snake_dto(...)` call turned into a spec, with its model imported for real."""
    where = f"{path}:{call.lineno}"
    if len(call.args) != 1 or not isinstance(call.args[0], ast.Name):
        raise SnakeDtoError(
            f"{where}: snake_dto() takes the MODEL CLASS as its only positional argument, written "
            f"as the name the file imports it under."
        )
    root = call.args[0].id
    model = _model(root, imports, where)
    name = _name(call, where)
    fields = _list(call, "fields")
    excluded = _list(call, "exclude")
    return build_spec(
        model=model,
        name=name,
        fields=None
        if fields is None
        else tuple(_pick(item, root, name, where) for item in fields),
        exclude=None
        if excluded is None
        else tuple(_pick(item, root, name, where).path for item in excluded),
        where=where,
    )


def _model(root: str, imports: dict[str, str], where: str) -> type:
    """The model class, resolved through the file's own import of it and then imported for real.

    Through the import and never through a registry index keyed by class name: two applications can
    each declare a `Customer`, and that index is kept by whichever registered last. The dotted path
    the user already wrote IS an identity, so the module is imported and the attribute read off it.
    """
    dotted = imports.get(root)
    if dotted is None:
        raise SnakeDtoError(
            f"{where}: {root!r} is not imported in this file, so there is no telling which model "
            f"it is. Add it under `if TYPE_CHECKING:` next to the declaration."
        )
    module_name, _, attribute = dotted.rpartition(".")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise SnakeDtoError(
            f"{where}: {root!r} comes from {module_name!r}, which cannot be imported: {error}."
        ) from error
    found = getattr(module, attribute, None)
    if not isinstance(found, type):
        raise SnakeDtoError(
            f"{where}: {module_name!r} has no class called {attribute!r}."
        )
    return found


def _name(call: ast.Call, where: str) -> str:
    """The `name=` keyword, which has to be a plain string literal to be readable without running."""
    for keyword in call.keywords:
        if keyword.arg == "name":
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
            raise SnakeDtoError(
                f"{where}: name= has to be a plain string literal. It is read out of the source "
                f"without running it, so an expression cannot be resolved."
            )
    raise SnakeDtoError(
        f"{where}: this declaration has no name=, and that is what the generated class is called."
    )


def _list(call: ast.Call, keyword: str) -> list[ast.expr] | None:
    """One of the two switches as a list of expressions, or `None` when it was not given."""
    for item in call.keywords:
        if item.arg == keyword:
            if not isinstance(item.value, ast.List):
                raise SnakeDtoError(
                    f"{keyword}= has to be written as a list literal, so it can be read without "
                    f"running the file."
                )
            return list(item.value.elts)
    return None


def _pick(entry: ast.expr, root: str, dto: str, where: str) -> SnakeDtoPick:
    """One selected entry: the path it names, and the DTO it was disambiguated with if any."""
    if isinstance(entry, ast.Tuple):
        if len(entry.elts) != 2 or not isinstance(entry.elts[1], ast.Constant):
            raise SnakeDtoError(
                f'{where}: a paired entry of {dto} is written `(Model.relation, "DtoName")`, '
                f"with the name as a plain string."
            )
        named = entry.elts[1].value
        if not isinstance(named, str):
            raise SnakeDtoError(
                f"{where}: the DTO name paired with an entry of {dto} has to be a string."
            )
        return SnakeDtoPick(path=_chain(entry.elts[0], root, dto, where), dto=named)
    return SnakeDtoPick(path=_chain(entry, root, dto, where))


def _chain(entry: ast.expr, root: str, dto: str, where: str) -> tuple[str, ...]:
    """The attribute chain an entry is written as, checked to start at the model being described.

    The ROOT check is the one that only reading can do. `snake_dto(Post, fields=[Author.id])`
    type-checks — `Author.id` is a valid expression — and the value it produces has forgotten it
    came from `Author`. `Post` has an `id` too, so resolving the evaluated path lands on the wrong
    column and says nothing.
    """
    steps: list[str] = []
    node = entry
    while isinstance(node, ast.Attribute):
        steps.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or not steps:
        raise SnakeDtoError(
            f"{where}: {dto} selects something that is not class access on a model. An entry is "
            f"written `Model.column`, `Model.relation.column` or `Model.relation`, so that the "
            f"type checker validates it where you wrote it."
        )
    if node.id != root:
        written = ".".join([node.id, *reversed(steps)])
        raise SnakeDtoError(
            f"{where}: {dto} describes {root} and selects {written}, which starts somewhere else. "
            f"Every entry has to be rooted at the model the declaration names."
        )
    return tuple(reversed(steps))
