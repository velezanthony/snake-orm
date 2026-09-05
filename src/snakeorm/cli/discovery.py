"""Finding the user's `SnakeOrmConfig` from wherever the CLI was invoked.

Nothing new is declared: the application's own entry point is imported and the config taken out of
it, because `--models` and `--dsn` would be a second source for a fact the config already holds.

- importing the entry module RUNS the `@snake_model` decorators, so the registry fills as a side
  effect of the import rather than as a separate step.
- the config is found by TYPE, not by name: it is the one `SnakeOrmConfig` instance in that module.

Each framework is recognised by ITS OWN convention:

| marker      | framework | how the config is reached                          |
|-------------|-----------|----------------------------------------------------|
| `manage.py` | Django    | `DJANGO_SETTINGS_MODULE` -> `config_from_django()` |
| `main.py`   | FastAPI   | import; the instance is in the module              |
| `app.py`    | Flask     | import; the instance is in the module              |
| `wsgi.py` / `asgi.py` | either | import; the instance is in the module      |

THE ONE CONDITION: the entry module has to be importable without doing work. Django settings are
constants and FastAPI puts its side effects in `lifespan`, so both are safe by construction; a Flask
app calling `create_app()` at import time is not. `SNAKEORM_CLI` is set before importing so an app
that must do work can tell who is asking.

`--config`, `--models` and `--dsn` win over anything found here, and finding nothing raises naming
every route it tried.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path
from types import ModuleType

from snakeorm.contrib.config import SnakeOrmConfig
from snakeorm.core.exceptions import SnakeConfigError

_DJANGO_MARKER = "manage.py"

_ENTRY_MARKERS: tuple[str, ...] = ("main.py", "app.py", "wsgi.py", "asgi.py")
"""Entry-point file names, in the order they are tried.

Each one is the framework's OWN convention and not our invention: `main.py` is what every FastAPI
tutorial and every `uvicorn main:app` uses, `app.py` is what Flask's CLI looks for on its own, and
`wsgi.py`/`asgi.py` are the deployment entry points both of them document.
"""

_MARKER_ENV = "SNAKEORM_CLI"
"""Set to `1` before importing the entry module, so an app can tell a tool from a real boot.

The escape hatch, not the mechanism. An application that has to do work at import time can guard it
with this instead of having its database rebuilt because somebody listed the tables.
"""

_SETTINGS_PATTERN = re.compile(r"""DJANGO_SETTINGS_MODULE["']\s*,\s*["']([\w.]+)["']""")


def find_config(explicit: str | None = None) -> SnakeOrmConfig:
    """The user's `SnakeOrmConfig`, by declared priority. It never guesses in silence.

    1. `--config module:NAME` (or just `module`), which always wins.
    2. `SNAKEORM_CONFIG` in the environment, same shape.
    3. The application's entry point, found by walking up from the working directory.

    With nothing to go on it raises, naming the three routes and what it looked for.
    """
    pointer = explicit or os.environ.get("SNAKEORM_CONFIG")
    if pointer:
        return _from_pointer(pointer)

    root, marker = _entry_point()
    if root is None or marker is None:
        raise SnakeConfigError(
            f"No SnakeORM configuration found. Three routes, in order: (1) --config "
            f"module:NAME, (2) the SNAKEORM_CONFIG environment variable, (3) an application "
            f"entry point in this directory or above it ({_DJANGO_MARKER} or one of "
            f"{', '.join(_ENTRY_MARKERS)}). None of them answered."
        )

    if root not in sys.path:
        # The project root goes on the path so its own imports resolve, which is what the caller
        # was doing by hand with PYTHONPATH.
        sys.path.insert(0, root)
    os.environ[_MARKER_ENV] = "1"

    if marker == _DJANGO_MARKER:
        return _from_django(Path(root) / marker)
    return _config_in(_import(Path(marker).stem, root, marker))


def _entry_point() -> tuple[str | None, str | None]:
    """`(project root, marker)` of the nearest application, walking up from the cwd.

    Django goes first at each level: a project can hold `manage.py` beside a `wsgi.py`, and the
    settings are the richer answer of the two.
    """
    for directory in (Path.cwd(), *Path.cwd().parents):
        if (directory / _DJANGO_MARKER).is_file():
            return str(directory), _DJANGO_MARKER
        for marker in _ENTRY_MARKERS:
            if (directory / marker).is_file():
                return str(directory), marker
    return None, None


def _from_django(manage: Path) -> SnakeOrmConfig:
    """Django's config, through the path Django itself documents.

    `manage.py` is where the settings module is named, so it is read from there rather than
    guessed. `django.setup()` touches no database: it loads settings and populates the app registry.
    """
    match = _SETTINGS_PATTERN.search(manage.read_text(encoding="utf-8"))
    if match is None:
        raise SnakeConfigError(
            f"{manage} does not name a DJANGO_SETTINGS_MODULE, so the settings that hold the "
            f"SnakeORM configuration cannot be located. Point at it with --config or set "
            f"DJANGO_SETTINGS_MODULE yourself."
        )
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", match.group(1))

    import django  # pyright: ignore[reportMissingImports]

    from snakeorm.contrib.django import config_from_django

    django.setup()
    return config_from_django()


def _from_pointer(pointer: str) -> SnakeOrmConfig:
    """`module:NAME` or `module`. With a name it is taken; without one it is found by type."""
    module_name, _, attribute = pointer.partition(":")
    module = importlib.import_module(module_name)
    if not attribute:
        return _config_in(module)
    found = getattr(module, attribute, None)
    if not isinstance(found, SnakeOrmConfig):
        raise SnakeConfigError(
            f"'{pointer}' is not a SnakeOrmConfig: {module_name}.{attribute} is "
            f"{type(found).__name__}."
        )
    return found


def _import(name: str, root: str, marker: str) -> ModuleType:
    """Import the entry module, turning an import-time failure into an explanation."""
    try:
        return importlib.import_module(name)
    except Exception as error:  # the app's own import, and its failures are the app's
        raise SnakeConfigError(
            f"Importing {marker} (in {root}) failed: {type(error).__name__}: {error}. The CLI "
            f"imports it because that import is what registers the models. A module that does "
            f"work when imported —opening connections, migrating, seeding— will fail here and "
            f"misbehave under a reloader too; move it behind an app factory or a lifespan hook, "
            f"or guard it with the {_MARKER_ENV} variable."
        ) from error


def _config_in(module: ModuleType) -> SnakeOrmConfig:
    """The single `SnakeOrmConfig` in the module, found by TYPE. Zero or several: it says so."""
    found = [
        (name, value)
        for name, value in vars(module).items()
        if isinstance(value, SnakeOrmConfig)
    ]
    if len(found) == 1:
        return found[0][1]
    if not found:
        raise SnakeConfigError(
            f"'{module.__name__}' holds no SnakeOrmConfig. That object is what carries the "
            f"connections and the migrations directory; build one there, or point at another "
            f"module with --config."
        )
    raise SnakeConfigError(
        f"'{module.__name__}' holds {len(found)} SnakeOrmConfig objects "
        f"({', '.join(name for name, _ in found)}). Name the one you mean with "
        f"--config {module.__name__}:<NAME>."
    )
