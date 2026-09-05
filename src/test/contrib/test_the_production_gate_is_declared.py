"""Turning on a channel that hands out SQL without declaring the environment is REFUSED.

The production flag used to be a plain `production: bool = False` on the WSGI and ASGI middlewares:
a permissive default, sitting next to a `channels` argument that reads itself out of the
environment. Two switches for one decision, one automatic and one manual, and the manual one
defaulted to the unsafe answer. That is how a demo came to ship `SNAKE_ORM_DEBUG=ssr` with nothing
to stop it.

`None` is a third state and not a synonym for development: it means NOBODY SAID. While no risky
channel is on it costs nothing and resolves to development, because there is no SQL to leak and
refusing would be noise. The moment one is on, the middleware refuses to start.

The Django adapter is deliberately absent from this file: it has `settings.DEBUG` to read, which is
the framework's own answer, and asking the user to repeat it would be a second source of truth.
"""

from __future__ import annotations

import pytest

from snakeorm.contrib.deliver import resolve_production
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.debug import RISKY_CHANNELS, SnakeDebugChannel, SnakeDebugConfig

_SAFE = frozenset(SnakeDebugChannel) - RISKY_CHANNELS


@pytest.mark.parametrize("channel", sorted(RISKY_CHANNELS))
def test_a_risky_channel_with_no_declared_environment_is_refused(
    channel: SnakeDebugChannel,
) -> None:
    """Every risky channel, one by one. Parametrised so a sixth one is covered the day it lands."""
    with pytest.raises(SnakeConfigError, match=channel.value):
        resolve_production(None, SnakeDebugConfig(), frozenset({channel}))


@pytest.mark.parametrize("channel", sorted(_SAFE))
def test_a_safe_channel_needs_no_declaration(channel: SnakeDebugChannel) -> None:
    """`timing` and `otel` carry no SQL, so silence about the environment costs nothing.

    Without this half the guard would be "declare the environment or the ORM will not start", which
    is a tax on every app that never turns the panel on.
    """
    assert resolve_production(None, SnakeDebugConfig(), frozenset({channel})) is False


def test_no_channels_at_all_needs_no_declaration() -> None:
    """Debug off is the overwhelmingly common case and must stay free."""
    assert resolve_production(None, SnakeDebugConfig(), frozenset()) is False


def test_the_config_answers_when_it_declares_an_environment() -> None:
    """A `SnakeDebugConfig(production=...)` is the declaration, and it is a TYPED field.

    It goes on the config object rather than into a dict of settings for the reason that object's
    own docstring gives: a dict returns `object` on every access and reintroduces the `Any` the
    project's thesis forbids. It grows by fields.
    """
    risky = frozenset({SnakeDebugChannel.SSR})

    assert resolve_production(None, SnakeDebugConfig(production=True), risky) is True
    assert resolve_production(None, SnakeDebugConfig(production=False), risky) is False


def test_the_explicit_argument_wins_over_the_config() -> None:
    """Someone already passing `production=` keeps working, and their answer is the last word."""
    config = SnakeDebugConfig(production=False)

    assert resolve_production(True, config, frozenset({SnakeDebugChannel.SSR})) is True


def test_the_refusal_names_the_variable_and_the_field() -> None:
    """The error says HOW to answer it, in both of the two places an answer can go.

    A refusal that only says "declare the environment" leaves the reader hunting for the spelling,
    and this one fires at startup, which is exactly when nobody has the source open.
    """
    with pytest.raises(SnakeConfigError) as caught:
        resolve_production(None, SnakeDebugConfig(), frozenset({SnakeDebugChannel.SSR}))

    message = str(caught.value)
    assert "SNAKE_ORM_PRODUCTION" in message
    assert "production=" in message
