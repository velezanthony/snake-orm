"""Scaled seeder tests: exact primary counts and determinism across runs."""

from __future__ import annotations

from collections.abc import Callable

from snakeorm import SnakeQuery, SnakeSession, count, snake_table

from shared.data import Scale, seed
from shared.models import (
    MODELS,
    Blog,
    Comment,
    Post,
    Tag,
    User,
    Visit,
)


def _count(session: SnakeSession, model: type) -> int:
    """Row count of a table (COUNT(*))."""
    return session.select(SnakeQuery(model), count())[0][0]


def test_seed_minimal_populates_primary_counts(seeded: SnakeSession) -> None:
    """The MINIMAL scale seeds EXACTLY the primary counts its `ScaleSpec` declares."""
    spec = Scale.MINIMAL.spec
    assert _count(seeded, User) == spec.users
    assert _count(seeded, Blog) == spec.blogs
    assert _count(seeded, Post) == spec.posts
    assert _count(seeded, Comment) == spec.comments
    assert _count(seeded, Visit) == spec.visits
    assert _count(seeded, Tag) == spec.tags


def test_seed_fills_every_table(seeded: SnakeSession) -> None:
    """None of the 29 tables is left empty: the whole graph gets populated, not only the primaries."""
    for model in MODELS:
        assert _count(seeded, model) > 0, f"empty table: {snake_table(model).name}"


def test_seed_is_deterministic(make_session: Callable[[], SnakeSession]) -> None:
    """The same scale produces the SAME counts over two seedings (RNG with a fixed seed)."""
    first = make_session()
    second = make_session()
    try:
        seed(first, Scale.MINIMAL)
        seed(second, Scale.MINIMAL)
        for model in MODELS:
            assert _count(first, model) == _count(second, model), snake_table(
                model
            ).name
    finally:
        first.close()
        second.close()
