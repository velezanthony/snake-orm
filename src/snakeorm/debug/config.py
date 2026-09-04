"""Debug panel settings, TYPE-FIRST: a dataclass of primitives, never a `dict[str, object]`.

A dict would return `object` on every access and reintroduce the `Any` that the project's thesis
forbids. This module is a LEAF (it only imports `DEFAULT_MIN_MS`, which lives in `advisor`), so it
can travel through the middleware, `deliver` and the panel without closing any import cycle.

Threshold resolution: the user's value (code or `.env`) → if there is none, ours
(`DEFAULT_MIN_MS`). `SnakeDebugConfig()` is the fallback; `from_env()` the default path;
constructing it, the typing.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from snakeorm.advisor import DEFAULT_MIN_MS

# Environment variable declaring the advisor threshold (ms). The `.env` loads it like any other.
ADVISE_MS_ENV_KEY = "SNAKE_ORM_ADVISE_MS"
# Environment variable declaring the language the panel OPENS in (`es`/`en`).
LANG_ENV_KEY = "SNAKE_ORM_LANG"
# Environment variable declaring WHERE this process runs. There is no default on purpose: see
# `production` below.
PRODUCTION_ENV_KEY = "SNAKE_ORM_PRODUCTION"
# What counts as "yes" in that variable. Anything else —including a typo— is NOT a declaration,
# so it falls through to the guard instead of quietly meaning "development".
_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


class SnakeDebugLanguage(Enum):
    """Language the debug panel OPENS in (the user changes it with the panel's 🌐 selector).

    A public tool → English by default. It is NOT library i18n and it drags in no dependencies: the
    panel already carries its ES/EN text table in its own JS (no `gettext`, no `.po`/`.mo`, no
    babel); this only picks which one it STARTS with. The HTTP headers (Server-Timing, W3C) are
    ALWAYS in English, untouched by this. The enum value is the BCP-47 code painted into
    `<html lang>` and into `data-lang`.
    """

    EN = "en"
    ES = "es"

    @classmethod
    def coerce(cls, value: str | None) -> SnakeDebugLanguage:
        """The language of `value` (`es`/`en`, case-insensitive), or English if it is `None` or
        unrecognised.

        It does not blow up on a strange value (a badly written `.env` or `settings.py` must not
        take down every request): it falls back to English, just as the advisor threshold falls
        back to its default.
        """
        if value is None:
            return cls.EN
        try:
            return cls(value.strip().lower())
        except ValueError:
            return cls.EN


def _language_from_env(env: Mapping[str, str]) -> SnakeDebugLanguage:
    """The `.env` language (`SNAKE_ORM_LANG`), or English if missing or unrecognised (no blow-up)."""
    return SnakeDebugLanguage.coerce(env.get(LANG_ENV_KEY))


def _production_from_env(env: Mapping[str, str]) -> bool | None:
    """Whether `SNAKE_ORM_PRODUCTION` declares an environment. `None` if it says nothing.

    UNLIKE the language, an unrecognised value does NOT fall back: it returns `None`, which the
    adapters turn into a refusal when a risky channel is on. Falling back here would mean a typo in
    the one variable that decides whether the SQL goes out on the response reads as "development",
    and the whole reason this is a tri-state is that nobody should be able to get that by accident.
    """
    raw = env.get(PRODUCTION_ENV_KEY)
    if raw is None:
        return None
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    return None


@dataclass(frozen=True, slots=True)
class SnakeDebugConfig:
    """Debug panel settings. It grows by typed FIELDS, not by keys of a dict.

    - `advise_min_ms`: the index advisor threshold. Below it, a query is so fast that an index
      changes nothing, so none is suggested. Default: ours (`DEFAULT_MIN_MS`).
    - `language`: the language the panel OPENS in. Default: English (a public tool).
    - `csp_nonce`: the nonce for the mounting script, when the app ships a strict CSP.

    The debug envelope (`snakeorm` in the JSON) is turned on by the `envelope` CHANNEL of
    `SNAKE_ORM_DEBUG`, not by a separate flag: if you declare the channel, it comes out in every
    response (in production it gets dropped for safety).
    """

    advise_min_ms: float = DEFAULT_MIN_MS
    language: SnakeDebugLanguage = SnakeDebugLanguage.EN
    production: bool | None = None
    """WHERE this process runs, which decides whether the risky channels get dropped.

    `None` means NOBODY SAID, and that is a third state on purpose — not a synonym for development.
    The adapters treat it as "development" only while no risky channel is on; the moment one is,
    they refuse to start and say so. A plain `False` default is what let a demo ship
    `SNAKE_ORM_DEBUG=ssr` and serve its SQL to the world, and the ORM's own doctrine is that a
    typo never falls back to a default.

    The Django adapter never needs this: it reads `settings.DEBUG`, which is the framework's own
    answer to the same question. WSGI and ASGI have nothing to ask — a middleware there receives the
    next callable in the chain, not the framework object — so the answer has to be declared.
    """

    csp_nonce: str | None = None
    """The nonce the panel's mounting script carries, for an app with a strict CSP.

    The panel is a `<template>` plus an inline `<script type="module">`; under `script-src 'self'`
    the browser blocks that script, the template never mounts, and the panel is simply not there —
    no error on the server, nothing in the page. A nonce is the mechanism CSP itself provides.

    The THREE adapters forward it through `transform_body`. It is FIXED for the process, though:
    only the Django one can read a per-response nonce (`request.csp_nonce`, from django-csp), and
    there it WINS over this. `None` keeps the output byte for byte.
    """

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SnakeDebugConfig:
        """Build the config from the environment (or a given map, for tests).

        Without the variable → our default (the user did not define it). An invalid value → the
        default too: a badly written `.env` must not blow up every request, only be ignored.
        """
        env = os.environ if environ is None else environ
        advise = DEFAULT_MIN_MS
        raw = env.get(ADVISE_MS_ENV_KEY)
        if raw is not None:
            try:
                advise = float(raw)
            except ValueError:
                advise = DEFAULT_MIN_MS
        return cls(
            advise_min_ms=advise,
            language=_language_from_env(env),
            production=_production_from_env(env),
        )
