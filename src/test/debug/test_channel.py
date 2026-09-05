"""Parsing `SNAKE_ORM_DEBUG` into a set of debug channels.

The config says WHICH deliveries get turned on; the user composes a subset of channels instead of
picking from a matrix of combinations. The canonical type is `frozenset[SnakeDebugChannel]`: repeats
impossible by construction (not by convention), immutable, and order is irrelevant (they are
independent toggles). An unknown name —typically a typo that would leave the dev WITHOUT debug while
thinking they have it— blows up loudly; a repeated one, harmless, collapses quietly.
"""

from __future__ import annotations

import pytest

from snakeorm.debug import (
    CHANNEL_AUDIENCE,
    RISKY_CHANNELS,
    SnakeDebugChannel,
    channels_from_env,
    demand_every_channel_classified,
    parse_channels,
)
from snakeorm.core.exceptions import SnakeConfigError


def test_parse_single_channel() -> None:
    """A single channel parses into a one-element frozenset."""
    assert parse_channels("envelope") == frozenset({SnakeDebugChannel.ENVELOPE})


def test_parse_multiple_channels() -> None:
    """Several comma-separated channels all parse, no matter the order."""
    assert parse_channels("ssr,envelope,timing") == frozenset(
        {
            SnakeDebugChannel.SSR,
            SnakeDebugChannel.ENVELOPE,
            SnakeDebugChannel.TIMING,
        }
    )


def test_duplicates_collapse() -> None:
    """A repeated channel collapses: the frozenset makes it impossible by construction."""
    assert parse_channels("ssr,ssr,ssr") == frozenset({SnakeDebugChannel.SSR})


def test_empty_string_is_off() -> None:
    """Empty string (or only commas/spaces) = debug off = empty frozenset."""
    assert parse_channels("") == frozenset()
    assert parse_channels("  ,  , ") == frozenset()


def test_whitespace_and_case_are_forgiven() -> None:
    """Surrounding spaces and uppercase do not break it: everything normalizes to lowercase."""
    assert parse_channels(" SSR , Envelope ") == frozenset(
        {SnakeDebugChannel.SSR, SnakeDebugChannel.ENVELOPE}
    )


def test_unknown_channel_raises_loud() -> None:
    """An unknown name (a typo) blows up with SnakeConfigError naming the channel: never in silence."""
    with pytest.raises(SnakeConfigError, match="envelopee"):
        parse_channels("ssr,envelopee")


def test_channels_from_env_reads_the_var() -> None:
    """channels_from_env reads SNAKE_ORM_DEBUG from the given environment mapping."""
    assert channels_from_env({"SNAKE_ORM_DEBUG": "timing,otel"}) == frozenset(
        {SnakeDebugChannel.TIMING, SnakeDebugChannel.OTEL}
    )


def test_channels_from_env_absent_is_off() -> None:
    """With the variable absent from the environment, debug stays off."""
    assert channels_from_env({}) == frozenset()


def test_otel_is_not_a_risky_channel() -> None:
    """`otel` stays OUT of the risky set, and that is the whole reason it is worth building.

    Its audience is `OPERATOR`: it goes out sideways to infrastructure the operator already runs.
    Filing it as risky would drop it in production, which is the only place a tracing channel
    justifies existing — that is declaring it dead.

    The reason this docstring no longer says "the risky ones are those that come back through the
    response" is that the sentence was false and load-bearing: `timing` comes back and is harmless,
    `ssr` came back and was not in the set. See the test above for the axis that actually decides.
    """
    assert SnakeDebugChannel.OTEL not in RISKY_CHANNELS


def test_the_channels_that_hand_sql_to_the_requester_are_the_risky_ones() -> None:
    """The risky set is every channel whose audience is the requester AND whose payload is SQL.

    This test used to assert `{envelope, sidecar}` and its name said "the ones that come back to the
    client" — two different predicates, and the gap between them is where `ssr` lived. `ssr` comes
    back to the client too, and `timing` does as well while being harmless, so "rides on the
    response" never was the axis. The axis is: does whoever asked end up holding the SQL?

    `ssr` answers yes, and louder than `envelope`: the panel paints every statement with the
    placeholders ALREADY REPLACED by their values, plus the `file:line` of the application code
    that fired them. It was not in the set, so a production deploy with `SNAKE_ORM_DEBUG=ssr` handed
    an anonymous `GET /` the schema, the data and a map of the source.
    """
    assert RISKY_CHANNELS == frozenset(
        {
            SnakeDebugChannel.SSR,
            SnakeDebugChannel.ENVELOPE,
            SnakeDebugChannel.SIDECAR,
        }
    )


def test_every_channel_declares_who_receives_it() -> None:
    """Every member of the enum has an audience. The risky set is DERIVED from it, not written out.

    A hand-written set fails in the open: what is missing from it reads as harmless, and nothing
    complains. Deriving it means a sixth channel cannot be risky-by-omission — it has to say who
    receives it before the module finishes importing.
    """
    assert set(CHANNEL_AUDIENCE) == set(SnakeDebugChannel)


def test_an_unclassified_channel_blows_up_instead_of_reading_as_harmless() -> None:
    """Forgetting to classify a channel is an error AT IMPORT, the same way `Cap` does it.

    This is the guard that the previous shape did not have. Without it the derivation would be just
    as silent as the literal it replaces: a channel absent from the map would simply not be risky.
    """
    with pytest.raises(SnakeConfigError, match="ssr"):
        demand_every_channel_classified(
            {
                channel: audience
                for channel, audience in CHANNEL_AUDIENCE.items()
                if channel is not SnakeDebugChannel.SSR
            }
        )


def test_the_panel_is_risky_and_the_timing_header_is_not() -> None:
    """The two halves of the axis, named. `timing` rides the response and carries no SQL.

    Without this pair, "everything on the response is risky" reads as an equally good rule, and it
    would kill a header whose whole point is being safe to leave on.
    """
    assert SnakeDebugChannel.SSR in RISKY_CHANNELS
    assert SnakeDebugChannel.TIMING not in RISKY_CHANNELS
