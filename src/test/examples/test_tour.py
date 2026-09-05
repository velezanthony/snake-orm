"""The examples/ tour runs IN FULL against a real Postgres and produces the expected output.

This is not an empty smoke test: besides checking that `main()` does not blow up and that it prints
the markers of the 22 sections, it checks concrete VALUES from the output (the deep JOIN, the
session count, the annotate average coerced to float, the UUID coercion, the nested any and the
columns inherited from the abstract base). If the ORM broke underneath, the tour would print
something else and these assertions would fail.

It skips gracefully if there is no Postgres (the same criterion as the rest of the scenarios).
"""

from __future__ import annotations

import psycopg2
import pytest

from test.conftest import NO_SERVER_REASON

from examples.tour import main
from test.scenarios.db import dsn

pytestmark = pytest.mark.integration


def _run_or_skip(capsys: pytest.CaptureFixture[str]) -> str:
    """Runs `main()` and returns its stdout; skips the test if Postgres is not reachable."""
    try:
        psycopg2.connect(dsn()).close()
    except psycopg2.OperationalError:  # pragma: no cover - depends on the environment
        pytest.skip(NO_SERVER_REASON)
    main()
    return capsys.readouterr().out


def test_tour_runs_and_prints_all_sections(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The tour runs in full without raising and prints the marker of the 22 sections and the closing."""
    output = _run_or_skip(capsys)
    for number in range(1, 23):
        assert f"SECTION {number}:" in output, f"section {number} is missing"
    assert "END OF THE TOUR" in output


def test_tour_reports_the_expected_concrete_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Checks CONCRETE values from the output, not just that it printed something.

    (1) the composite deep JOIN returns the three Spanish print runs; (2) `session.count()` gives 5
    books; (3) `annotate()` coerces Anaya's average to float (16.245); (4) the projected UUID
    column comes back as uuid.UUID; (5) the nested `any()` locates Germany; (6) the nested include
    (SnakePrefetch) emits 3 queries (one per level), not one per parent; (7) ExTag inherits
    id + created_at from the abstract base, in that order and before its own column.
    """
    output = _run_or_skip(capsys)
    assert "print runs (copies) published in Spain: [1000, 2000, 1500]" in output
    assert "total books: 5" in output
    assert "Anaya      -> books=2  mean=16.245 (float)" in output
    assert "type(value).__name__: 'UUID'" in output
    assert "countries with an expensive bestseller: ['Alemania']" in output
    assert "no N+1): 3" in output
    assert "columns inherited by ex_tags: ['id', 'created_at', 'label']" in output
    # (8) the read-only VIEW navigates from the view to the model: 'Don Quixote' is Anaya's.
    assert "publisher of 'Don Quixote' (view -> model): 'Anaya'" in output
    assert "catalogue of Anaya: ['Don Quixote', 'Novelas ejemplares']" in output
    # (9) session.call() over the ex_book_stats function: Anaya (publisher_id 1) has 2 books that
    # add up to 32.49, and the total comes back as float (NUMERIC→float coercion of the declared type).
    assert "publisher 1: (2, 32.49)" in output
    # Filtered prefetch: Anaya has books but none expensive -> [] (and it still COMES); Springer does.
    assert "expensive books of Anaya: []" in output
    assert (
        "expensive books of Springer: "
        "['Database System Concepts', 'Introduction to Algorithms']" in output
    )
