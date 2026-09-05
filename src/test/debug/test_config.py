"""Tests for `SnakeDebugConfig`: the debug panel settings, type-first (a dataclass, not a dict).

The index advisor threshold resolves like this: the user's value (code or `.env`) → if there is none,
ours (`DEFAULT_MIN_MS`). `from_env` is the default path; building the dataclass is the typed path in
code. An invalid value in the environment does NOT blow up: it falls back to the default.
"""

from __future__ import annotations

from snakeorm.advisor import DEFAULT_MIN_MS
from snakeorm.debug import SnakeDebugConfig, SnakeDebugLanguage


def test_default_threshold_is_ours() -> None:
    """With nothing configured, the threshold is ours (`DEFAULT_MIN_MS`)."""
    assert SnakeDebugConfig().advise_min_ms == DEFAULT_MIN_MS


def test_from_env_reads_the_user_threshold() -> None:
    """`from_env` reads the user's threshold from `SNAKE_ORM_ADVISE_MS`."""
    config = SnakeDebugConfig.from_env({"SNAKE_ORM_ADVISE_MS": "25"})
    assert config.advise_min_ms == 25.0


def test_from_env_without_the_var_falls_back_to_ours() -> None:
    """With the variable absent, `from_env` falls back to our default (the user did not define it)."""
    assert SnakeDebugConfig.from_env({}).advise_min_ms == DEFAULT_MIN_MS


def test_from_env_ignores_a_garbage_value() -> None:
    """A non-numeric value in the environment does NOT blow up: it falls back to the default instead of breaking the request."""
    assert (
        SnakeDebugConfig.from_env({"SNAKE_ORM_ADVISE_MS": "nope"}).advise_min_ms
        == DEFAULT_MIN_MS
    )


def test_is_frozen() -> None:
    """The config is immutable (frozen): a setting does not get overwritten mid-request."""
    config = SnakeDebugConfig(advise_min_ms=50.0)
    try:
        config.advise_min_ms = 1.0  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("SnakeDebugConfig debería ser frozen")


def test_default_language_is_english() -> None:
    """A public tool → the panel OPENS in English by default (it matches the JS default)."""
    assert SnakeDebugConfig().language is SnakeDebugLanguage.EN


def test_from_env_reads_the_user_language() -> None:
    """`from_env` reads the user's language from `SNAKE_ORM_LANG` (case-insensitive)."""
    assert (
        SnakeDebugConfig.from_env({"SNAKE_ORM_LANG": "ES"}).language
        is SnakeDebugLanguage.ES
    )


def test_from_env_without_the_lang_var_defaults_to_english() -> None:
    """With the variable absent, `from_env` falls back to English (the user did not define it)."""
    assert SnakeDebugConfig.from_env({}).language is SnakeDebugLanguage.EN


def test_from_env_ignores_an_unknown_language() -> None:
    """An unsupported language does NOT blow up: it falls back to English instead of breaking the request."""
    assert (
        SnakeDebugConfig.from_env({"SNAKE_ORM_LANG": "kling"}).language
        is SnakeDebugLanguage.EN
    )


def test_language_code_is_bcp47() -> None:
    """The enum value is the BCP-47 code that goes in `<html lang>` and in the panel's `data-lang`."""
    assert SnakeDebugLanguage.EN.value == "en"
    assert SnakeDebugLanguage.ES.value == "es"
