"""The benchmark harness runs IN FULL against a real Postgres with SMALL sizes.

This test keeps the benchmark alive: it does not check TIMINGS (they vary per machine), only that
`main()` runs without raising, returns 0 and emits the seven expected sections plus the final
table. It uses `SMALL_CONFIG` (small N) to stay fast. It skips gracefully when there is no
Postgres, just like the rest of the integration scenarios.
"""

from __future__ import annotations

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from benchmarks.harness import SMALL_CONFIG
from benchmarks.run import main
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


def _run_or_skip(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """Runs `main(SMALL_CONFIG)` and returns (exit code, stdout); skips without Postgres."""
    try:
        psycopg2.connect(dsn()).close()
    except psycopg2.OperationalError:  # pragma: no cover - depends on the environment
        pytest.skip(NO_SERVER_REASON)
    code = main(SMALL_CONFIG)
    return code, capsys.readouterr().out


def test_benchmark_runs_and_prints_all_sections(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The benchmark runs in full, returns 0 and prints the seven sections and the results table."""
    code, output = _run_or_skip(capsys)
    assert code == 0
    for marker in (
        "1. Compilation",
        "2. SQL emission",
        "3. INSERT",
        "4. Plain SELECT",
        "5. SELECT deep navigation",
        "6. to-many include",
        "7. annotate / aggregate",
        "Results",
    ):
        assert marker in output, f"section missing: {marker}"


def test_benchmark_include_is_not_n_plus_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The to-many include emits exactly 2 queries (1 root + 1 select-in), NEVER N+1."""
    _, output = _run_or_skip(capsys)
    assert "2 queries emitted" in output
    assert "NOT an N+1" in output
