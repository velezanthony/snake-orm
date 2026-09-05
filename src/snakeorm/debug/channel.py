"""Debug delivery channels and the parsing of `SNAKE_ORM_DEBUG`.

A channel is a DELIVERY mode of the same report; they compose as a `frozenset[SnakeDebugChannel]`. The environment string is only their serialisation.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum, StrEnum

from snakeorm.core.exceptions import SnakeConfigError

DEBUG_ENV_KEY = "SNAKE_ORM_DEBUG"
"""Environment variable that turns the channels on, as a comma-separated list."""


class SnakeDebugChannel(StrEnum):
    """How the report is DELIVERED. Independent channels that combine freely; each contrib applies only the ones that make sense in its framework."""

    SSR = "ssr"  # an HTML panel injected into the response (Django/Flask)
    ENVELOPE = "envelope"  # a `snakeorm` block in the JSON + a text table — NO tooling (Postman)
    TIMING = "timing"  # a Server-Timing header — WITH tooling (the browser devtools)
    SIDECAR = "sidecar"  # a token + its own page at /__snake__/{token}
    OTEL = "otel"  # OpenTelemetry spans over OTLP — WITH tooling (Jaeger/Grafana)


class ChannelAudience(Enum):
    """WHO ends up holding what a channel delivers. It is the axis that decides risk.

    The set of risky channels used to be written out by hand as `{envelope, sidecar}`, under the
    heading "the ones that come back to the client". That heading is not the rule it was standing
    in for: `ssr` comes back to the client too, and `timing` also does while being harmless. `ssr`
    was missing, and what is missing from a hand-written set reads as harmless without anyone
    deciding so — which is how a production deploy came to hand its SQL to anonymous visitors.

    The real question is two-part, and this enum asks both halves: who receives it, and does what
    they receive contain the SQL.
    """

    CLIENT_SQL = "client_sql"
    """The requester gets the statements themselves. Never in production."""

    CLIENT_METRICS = "client_metrics"
    """The requester gets timings and counts, no SQL. Safe to leave on."""

    OPERATOR = "operator"
    """It goes out SIDEWAYS, to infrastructure the operator already runs — never on the response."""


CHANNEL_AUDIENCE: Mapping[SnakeDebugChannel, ChannelAudience] = {
    # The panel paints every statement with the placeholders ALREADY REPLACED by their values, plus
    # the `file:line` of the application code that fired them. Strictly MORE than the envelope.
    SnakeDebugChannel.SSR: ChannelAudience.CLIENT_SQL,
    SnakeDebugChannel.ENVELOPE: ChannelAudience.CLIENT_SQL,
    SnakeDebugChannel.SIDECAR: ChannelAudience.CLIENT_SQL,
    # A `Server-Timing` header: how long, not what. It is the one delivery worth leaving on.
    SnakeDebugChannel.TIMING: ChannelAudience.CLIENT_METRICS,
    # Spans over OTLP, to the operator's own collector. Production is the ONLY place a tracing
    # channel justifies existing, so filing it as risky would be declaring it dead.
    SnakeDebugChannel.OTEL: ChannelAudience.OPERATOR,
}
"""Who receives each channel. Exhaustive by construction — see the guard right below."""


def demand_every_channel_classified(
    audience: Mapping[SnakeDebugChannel, ChannelAudience],
) -> None:
    """Blows up if a channel of the enum has no audience declared. Runs AT IMPORT.

    Same mechanism the capability catalogue uses (`SnakeCapabilities.__post_init__`) and for the
    same reason: a channel that nobody classified would simply not be risky, which is precisely the
    silence this module exists to prevent. Declaring the audience is not paperwork — it is the only
    moment somebody is forced to think about who ends up with the SQL.
    """
    missing = [
        channel.value for channel in SnakeDebugChannel if channel not in audience
    ]
    if missing:
        raise SnakeConfigError(
            f"These debug channels do not declare who receives them: {', '.join(missing)}. "
            f"Every channel declares an audience: an unclassified one would read as harmless "
            f"and would survive the production filter without anyone having decided so."
        )


demand_every_channel_classified(CHANNEL_AUDIENCE)

RISKY_CHANNELS: frozenset[SnakeDebugChannel] = frozenset(
    channel
    for channel, audience in CHANNEL_AUDIENCE.items()
    if audience is ChannelAudience.CLIENT_SQL
)
"""Channels that hand the SQL to whoever asked: dropped in production even if configured.

DERIVED, never written out. The literal it replaces was missing `ssr` and nothing could tell."""

# Channels that are DECLARED but not built yet. Enabling one delivers nothing, so it WARNS instead
# of failing silently. It is EMPTY today: `otel` was the last one in it and now exports for real
# (`debug/otel/`). The mechanism stays for the next channel declared ahead of its exporter; what
# does not stay is a warning telling users that a working channel delivers nothing.
UNIMPLEMENTED_CHANNELS: frozenset[SnakeDebugChannel] = frozenset()


def parse_channels(raw: str) -> frozenset[SnakeDebugChannel]:
    """Parse `"ssr,envelope"` into a `frozenset`. Empty → off; spaces/uppercase are forgiven.

    An UNKNOWN name blows up naming it: a typo that silently left you without debug is precisely the failure being fought.
    """
    channels: set[SnakeDebugChannel] = set()
    for token in raw.split(","):
        name = token.strip().lower()
        if not name:
            continue
        try:
            channels.add(SnakeDebugChannel(name))
        except ValueError:
            valid = ", ".join(channel.value for channel in SnakeDebugChannel)
            raise SnakeConfigError(
                f"Unknown debug channel: '{name}'. "
                f"{DEBUG_ENV_KEY} accepts these channels: {valid}."
            ) from None
    return frozenset(channels)


def channels_from_env(
    environ: Mapping[str, str] | None = None,
) -> frozenset[SnakeDebugChannel]:
    """Read `SNAKE_ORM_DEBUG` from the environment (or the given map, for tests) and parse it into channels."""
    env = os.environ if environ is None else environ
    return parse_channels(env.get(DEBUG_ENV_KEY, ""))
