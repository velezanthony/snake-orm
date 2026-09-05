"""Framework-NATIVE ways of invoking the same CLI. Adapters, with no logic of their own.

The `snakeorm` executable works everywhere and is the agnostic answer. This module is the other
half: it lets somebody type the command the way their framework taught them —`manage.py snakeorm`,
`flask snakeorm`— and reach the SAME `main()`. One core, one adapter per framework.

The discipline that makes that shape work: **an adapter parses nothing, decides nothing and
defaults nothing.** It hands the arguments over and returns the exit code. An adapter that starts
interpreting its own arguments drifts from the core it was adapting.

Which is also why FastAPI is absent, and that is not an oversight. Django has `manage.py` and Flask
has `app.cli`; FastAPI has no command line of its own — `uvicorn main:app` is an argument to another
program, not a hook. So FastAPI uses the executable, which already needs nothing configured.

It lives in `cli/` and not in `contrib/`, and the acyclicity net is what said so: `cli` already
imports `contrib` to reach `SnakeOrmConfig`, so an adapter sitting in `contrib` and importing the
CLI closed a circle between the two packages. The dependency runs one way.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def run(argv: Sequence[str]) -> int:
    """The single door every adapter goes through. Imported lazily so a hook costs nothing."""
    from snakeorm.cli import main

    return main(list(argv))


class SnakeOrmCommand:
    """Django management command. Put ONE line in your project and every subcommand is there:

        # myapp/management/commands/snakeorm.py
        from snakeorm.contrib.cli_hooks import SnakeOrmCommand as Command

    Django demands the file live at that path and the class be called `Command`, so the line cannot
    be avoided — but it holds no logic, which is the part that matters. `run_from_argv` is
    overridden rather than `handle` on purpose: Django would otherwise parse the arguments with its
    own `argparse` and reject the ones it does not know, so the subcommand's flags would have to be
    declared a second time here. Taking the raw `argv` keeps ONE parser, in the core, and means a
    flag added there works from `manage.py` on the same day.

    It does not subclass `BaseCommand`: Django accepts any object with `run_from_argv`, and not
    importing Django keeps this module importable without it.
    """

    help = "Run the SnakeORM CLI (makemigrations, migrate, tables, ...)."

    def run_from_argv(self, argv: Sequence[str]) -> None:
        """`['manage.py', 'snakeorm', 'tables', '--detail']` -> the core gets `['tables', '--detail']`."""
        raise SystemExit(run(argv[2:]))

    def print_help(self, prog_name: str, subcommand: str) -> None:
        """`manage.py help snakeorm` shows the CORE's help, not a second one written here."""
        run(["--help"])


def flask_command() -> Any:
    """A `click` command that carries the CLI into `flask`. Register it on your app:

        from snakeorm.contrib.cli_hooks import flask_command

        app.cli.add_command(flask_command())

    Then `flask snakeorm tables` works beside `flask run`. `ignore_unknown_options` plus
    `UNPROCESSED` is what stops click from reading the arguments: they travel untouched to the one
    parser that knows them.

    `click` is imported inside, because it arrives with Flask and this module has to import without
    either of them.
    """
    import click

    @click.command(
        "snakeorm",
        context_settings={"ignore_unknown_options": True, "help_option_names": []},
        help=SnakeOrmCommand.help,
    )
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def snakeorm(args: tuple[str, ...]) -> None:
        raise SystemExit(run(args))

    return snakeorm
