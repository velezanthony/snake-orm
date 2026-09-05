"""Showcase tests: the panel must CATCH the two anti-patterns `dashboard_page` commits on purpose —
the LITERAL duplicate (the same query twice) and the N+1 (the same SQL in a loop).

This is the proof that the tool does what the user wants: telling "I ran the same query twice by
accident" apart from "I ran N queries in a loop".
"""

from __future__ import annotations

from collections.abc import Callable

from snakeorm import SnakeSession
from snakeorm.debug import DuplicateGroup

from shared.data import Scale
from shared.showcase import capture_dashboard


def _find_duplicate(
    duplicates: tuple[DuplicateGroup, ...], predicate: Callable[[str], bool]
) -> DuplicateGroup | None:
    """First group of the duplicate list whose SQL satisfies the predicate, or `None`."""
    return next((group for group in duplicates if predicate(group.sql)), None)


def test_dashboard_detects_literal_duplicate(seeded: SnakeSession) -> None:
    """The sidebar repeats the SAME published-posts query as the header: the panel flags it x2.

    This is the LITERAL duplicate (same SQL, same params), NOT an N+1: it tells them apart by text.
    Both reads reach the same `catalog` line, so the call-site half of the key holds them together.
    """
    duplicates = capture_dashboard(seeded).duplicates()
    published = _find_duplicate(
        duplicates, lambda sql: 'FROM "posts"' in sql and 'WHERE "published"' in sql
    )
    assert published is not None, (
        "the literal duplicate of published posts was not detected"
    )
    assert published.count == 2, (
        "the header's query and the sidebar's should add up to 2"
    )


def test_dashboard_detects_n_plus_one(seeded: SnakeSession) -> None:
    """Asking for tokens user by user in a loop leaves N copies of the SAME SQL: N = user count."""
    duplicates = capture_dashboard(seeded).duplicates()
    tokens = _find_duplicate(duplicates, lambda sql: '"api_tokens"' in sql)
    assert tokens is not None, "the tokens N+1 was not detected"
    assert tokens.count == Scale.MINIMAL.spec.users, (
        "one tokens query per user (an N+1)"
    )


def test_dashboard_emits_warnings(seeded: SnakeSession) -> None:
    """Every duplicated SQL raises a readable possible-N+1 warning: the panel does not swallow them."""
    report = capture_dashboard(seeded)
    assert report.warnings, "it should warn about the duplicate queries"
    assert len(report.warnings) == len(report.duplicates())
    assert all("N+1" in warning for warning in report.warnings)
