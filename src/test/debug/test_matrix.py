"""The channel × framework validation matrix: which channel has an effect on which framework.

It is not a matrix of COMBINATIONS to pick from (that would be combinatorial explosion); it is a
FINITE table (5 channels × 3 frameworks) that validates the user's set. `SSR` on an API app is the
only no-op: there is no HTML to inject into. And a no-op is not swallowed in silence —it warns—, the
same lesson as the index bug: a silence reads as "it is covered".
"""

from __future__ import annotations

import warnings

import pytest

from snakeorm.debug import (
    UNIMPLEMENTED_CHANNELS,
    SnakeDebugChannel,
    SnakeWebFramework,
    channels_without_effect,
    warn_unimplemented,
    warn_unsupported,
)
from snakeorm.core.exceptions import SnakeWarning


def test_ssr_has_no_effect_on_fastapi() -> None:
    """`ssr` does not apply on FastAPI (API-only): it comes out as a channel without effect."""
    channels = frozenset({SnakeDebugChannel.SSR, SnakeDebugChannel.ENVELOPE})
    assert channels_without_effect(channels, SnakeWebFramework.FASTAPI) == frozenset(
        {SnakeDebugChannel.SSR}
    )


def test_ssr_works_on_django_and_flask() -> None:
    """`ssr` does have an effect on Django and Flask: there are no channels without effect."""
    channels = frozenset({SnakeDebugChannel.SSR, SnakeDebugChannel.ENVELOPE})
    assert channels_without_effect(channels, SnakeWebFramework.DJANGO) == frozenset()
    assert channels_without_effect(channels, SnakeWebFramework.FLASK) == frozenset()


def test_warn_unsupported_emits_snake_warning() -> None:
    """A channel without effect fires a SnakeWarning that names it."""
    channels = frozenset({SnakeDebugChannel.SSR})
    with pytest.warns(SnakeWarning, match="ssr"):
        warn_unsupported(channels, SnakeWebFramework.FASTAPI)


def test_warn_unsupported_is_silent_when_all_ok() -> None:
    """With no channels without effect, no warning is emitted."""
    channels = frozenset({SnakeDebugChannel.ENVELOPE, SnakeDebugChannel.TIMING})
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning would be a failure
        warn_unsupported(channels, SnakeWebFramework.FASTAPI)


def test_nothing_is_unimplemented_any_more() -> None:
    """EVERY declared channel delivers something today, `otel` included: the set is empty.

    The net stays because the next channel to be declared before it is built needs it. What it can
    no longer do is warn about a channel that works — `otel` sat in that set from the day it was
    declared, and a warning saying "switching it on delivers nothing" outlives its truth in silence.
    """
    assert UNIMPLEMENTED_CHANNELS == frozenset()


@pytest.mark.parametrize("channel", list(SnakeDebugChannel))
def test_warn_unimplemented_is_silent_for_every_channel(
    channel: SnakeDebugChannel,
) -> None:
    """No channel fires the 'not implemented' warning, named one by one so a failure names it."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning would be a failure
        warn_unimplemented(frozenset({channel}))
