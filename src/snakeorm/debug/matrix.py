"""Channel × framework validation: which delivery makes sense where.

The only real rule: `SSR` (injecting HTML) only applies where the server renders HTML (Django/Flask); in an API app it is a no-op that gets WARNED about, not swallowed.
"""

from __future__ import annotations

import warnings
from enum import StrEnum

from snakeorm.debug.channel import UNIMPLEMENTED_CHANNELS, SnakeDebugChannel
from snakeorm.core.exceptions import SnakeWarning


class SnakeWebFramework(StrEnum):
    """The web framework a contrib hooks into. It fixes which channels have any effect."""

    DJANGO = "django"
    FLASK = "flask"
    FASTAPI = "fastapi"


# Frameworks that render server-side HTML and can therefore INJECT the panel (the SSR channel).
_SSR_CAPABLE = frozenset({SnakeWebFramework.DJANGO, SnakeWebFramework.FLASK})


def channels_without_effect(
    channels: frozenset[SnakeDebugChannel],
    framework: SnakeWebFramework,
) -> frozenset[SnakeDebugChannel]:
    """The requested channels that have NO effect on that framework (today only `SSR` outside a framework with server-side HTML rendering)."""
    if framework in _SSR_CAPABLE:
        return frozenset()
    return channels & frozenset({SnakeDebugChannel.SSR})


def warn_unsupported(
    channels: frozenset[SnakeDebugChannel],
    framework: SnakeWebFramework,
) -> None:
    """Emit a `SnakeWarning` per channel with no effect on the framework. Silence if it all adds up."""
    for channel in sorted(channels_without_effect(channels, framework)):
        warnings.warn(
            f"The debug channel '{channel.value}' has no effect on {framework.value}: "
            f"there is no server HTML to inject the panel into. Use 'sidecar' for a visual "
            f"panel in an API app.",
            SnakeWarning,
            stacklevel=2,
        )


def warn_unimplemented(channels: frozenset[SnakeDebugChannel]) -> None:
    """Warn about enabled channels that do not deliver anything yet (today, `otel`): never fail silently."""
    for channel in sorted(channels & UNIMPLEMENTED_CHANNELS):
        warnings.warn(
            f"The debug channel '{channel.value}' is declared but not implemented yet: "
            f"switching it on delivers nothing so far.",
            SnakeWarning,
            stacklevel=2,
        )
