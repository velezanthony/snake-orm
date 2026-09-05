"""The ASYNCHRONOUS twin of `shared/usecases/`: the same operations, driven by an `AsyncSession`.

WHY THIS PACKAGE EXISTS AT ALL, since a second copy of a domain layer is exactly what this
repository has been burned by twice. Because Python's `await` is syntax, not a value: one function
body cannot serve a blocking session and an awaiting one, and no amount of design gets around it.
The question is therefore not "how do we avoid a second layer" but "how thin can the second layer
be made, and what guards it".

**How thin.** Everything that CAN be colourless is. A `SnakeQuery` is a value: building one runs
nothing, so every read in the demo is a fragment in `shared/selectors/` and both colours execute the
same object. An INSTANCE is a value too, so a `Role(name=...)` is built by the same code on both
paths. What is left over here is the CONTROL FLOW — validate, look up, decide, write, commit — which
is two or three lines per use case and is the only thing that gets typed twice.

**What guards it.** Two nets, both under `shared/tests/`:

- `test_async_mirror.py` compares the two layers STRUCTURALLY: same modules, same function names,
  same parameters. A use case that gains a colour and not its twin fails there, which is what stops
  the asynchronous demo from quietly answering fewer questions than the synchronous one.
- `test_sync_async_parity.py` compares them BEHAVIOURALLY: the same question asked of both sessions
  has to give the same answer, emit the same SQL with the same parameters, and produce the same
  warning text out of the ORM. The message is compared as well as the SQL on purpose — this project
  already watched two sessions drift into two wordings of one complaint while a SQL-only check
  passed.

**What was rejected, and why.** Wrapping the synchronous layer in `asyncio.to_thread` would have
cost nothing and would have kept the event loop free, which is a real property — but it exercises
`SnakeSession` on a worker thread, so `AsyncSession`, the async drivers and the async pool would
still have no caller outside `src/test`, and giving them one is the entire point of the exercise. A
sans-io domain layer —use cases written as generators that yield queries and are run by a driver per
colour— genuinely solves the colour problem and was rejected for a different reason: these demos
exist to be read and copied, and nobody writes an application that way.
"""

import importlib
import pkgutil
from types import FunctionType, ModuleType

_SUFFIX = "_usecases"


def modules() -> dict[str, ModuleType]:
    """Every asynchronous domain module, by domain name, DISCOVERED rather than listed.

    A hand-kept list would be a second place to remember, and the nets in `shared/tests/` exist
    precisely because somebody adds an operation and forgets the other half — an inventory written by
    the same hand would be forgotten in the same way. Dropping a `<domain>_usecases.py` in here is
    enough to put it under both nets.
    """
    return {
        info.name.removesuffix(_SUFFIX): importlib.import_module(
            f"{__name__}.{info.name}"
        )
        for info in sorted(pkgutil.iter_modules(__path__), key=lambda info: info.name)
        if info.name.endswith(_SUFFIX)
    }


def public_functions() -> dict[str, tuple[str, ...]]:
    """Every asynchronous use case, by domain: what the nets in `shared/tests/` enumerate.

    Only functions DEFINED in the module count — an imported fragment or helper is somebody else's
    function that happens to be visible from here, and counting it would have the nets demanding a
    synchronous twin of `SnakeQuery`.
    """
    return {
        domain: tuple(
            sorted(
                name
                for name, value in vars(module).items()
                if not name.startswith("_")
                and isinstance(value, FunctionType)
                and value.__module__ == module.__name__
            )
        )
        for domain, module in modules().items()
    }


def __getattr__(name: str) -> ModuleType:
    """`aio.blog_usecases` without an import line per domain, so adding one touches no file but its own.

    Python calls this only for attributes the module does not already have, which is every domain
    module until something imports it. It is the same discovery `modules()` does, reached through
    the syntax a caller would rather write.
    """
    if name.endswith(_SUFFIX):
        return importlib.import_module(f"{__name__}.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
