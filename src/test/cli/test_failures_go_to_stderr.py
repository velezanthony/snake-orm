"""The CLI's failures go to STDERR, and they carry what the engine said.

`rg -n "stderr" src/snakeorm/` returned nothing at all: every message the package prints, error or
not, went to stdout. So `snakeorm migrate --database prod > migration.log` puts the failure INSIDE
the file it was told to write, the `2>&1` of the calling script captures nothing, and CI is left
with an exit code and no context.

The second half is the cause. `migration/runner.py` builds its `SnakeMigrationError` with
`from error` but does NOT interpolate the engine's words into the message, so what reaches the user
is "failed after applying 2 of 5" with nothing about WHY. The `__cause__` of that exception is
`column "slug" already exists` — the one piece of information the command was run to obtain.

It is printed ALWAYS rather than behind a `--traceback`: a flag you have to know about is a flag
nobody sets on the run that already failed.

WHAT DOES NOT MOVE: the things that are an ANSWER. `snakeorm check > drift.txt` is a CI writing the
drift report to a file, and "Drift detected (3)" is that report, not an error.
"""

from __future__ import annotations

import pytest

from snakeorm.cli.app import main
from snakeorm.core.exceptions import SnakeConfigError


def test_an_error_goes_to_stderr_and_not_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The failure lands on stderr. Redirecting stdout must not swallow it."""
    code = main(["migrate", "--database", "nope-there-is-no-such-alias"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("Error: "), "the failure did not reach stderr at all"
    assert captured.out == "", (
        "the error went out through stdout: a `> file.log` would have swallowed it"
    )


def test_the_engines_own_words_travel_with_the_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When a `SnakeError` has a cause, the cause is printed too.

    Without it the user reads our summary of the failure and never the failure. `from error` keeps
    the chain for a traceback nobody sees on a CLI, and the message the CLI actually prints is
    `str(error)` — which is the summary alone.
    """
    original = ValueError('column "slug" already exists')
    wrapped = SnakeConfigError("the migration stopped after applying 2 of 5")
    wrapped.__cause__ = original

    from snakeorm.cli.app import report_failure

    report_failure(wrapped)

    captured = capsys.readouterr()
    assert "applying 2 of 5" in captured.err
    assert 'column "slug" already exists' in captured.err, (
        "the engine's own words were dropped: they are what the command was run to find out"
    )


def test_a_failure_writes_nothing_at_all_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The floor in the other direction: reporting a failure must not touch stdout.

    Moving everything to stderr would be the same mistake mirrored — `snakeorm check > drift.txt` is
    a CI writing a report and the report is not an error — so this pins only the failure path.
    """
    from snakeorm.cli.app import report_failure

    report_failure(SnakeConfigError("boom"))

    captured = capsys.readouterr()
    assert "boom" in captured.err
    assert captured.out == "", "an error wrote to stdout"
