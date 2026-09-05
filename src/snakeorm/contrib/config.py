"""SHARED translators: from a framework's native config (dicts) to the centralised config.

The logic has NOTHING of any concrete framework in it —it is dict → `SnakeConnectionConfig` /
(channels, panel config)—, so it lives here and `contrib.django`, the only framework linker, uses
it. The TypedDicts type the SHAPE of the dict the user writes, for IntelliSense. Everything fails
LOUD: an unknown `ENGINE`/channel or a non-numeric threshold blows up naming them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, TypedDict

from snakeorm.advisor import DEFAULT_MIN_MS
from snakeorm.connection import SnakeBackend, SnakeConnectionConfig
from snakeorm.core.exceptions import SnakeConfigError
from snakeorm.debug import (
    AsyncCaptureDriver,
    CaptureDriver,
    SnakeDebugChannel,
    SnakeDebugConfig,
    SnakeDebugLanguage,
    parse_channels,
)

if TYPE_CHECKING:
    from snakeorm.session import AsyncSession, SnakeSession


def open_session(config: SnakeConnectionConfig) -> SnakeSession:
    """Open a session from the central config, with the captured driver (the panel sees the SQL).

    The UNIVERSAL path: whoever builds a `SnakeConnectionConfig` directly (Flask, FastAPI, or
    wherever) injects it into their app and opens with this. A framework WITHOUT a connection
    convention needs no bespoke linker —only Django has one, because its `DATABASES` IS a convention
    to translate—.

    The `backend` also DECLARES the engine to the capture driver, so every record knows which engine
    ran it — `db.system.name`, which the `otel` channel puts on every query span. It is declared and
    not guessed: a pooled or timed-out driver hides its class, and no SQL tells MySQL from MariaDB.
    """
    system = config.backend.db_system_name
    return config.open(wrap=lambda driver: CaptureDriver(driver, system=system))


async def open_session_async(config: SnakeConnectionConfig) -> AsyncSession:
    """The same path, awaited: an ASYNCHRONOUS session from the central config with the SQL captured.

    It exists for the same reason as its sibling: an async framework building a
    `SnakeConnectionConfig` had to assemble driver and dialect by hand, and lost the debug panel
    along the way. That the facade is a single line is precisely the sign that the seam was in the
    right place.

    The engine is declared here too: one seam, the same two colours.
    """
    system = config.backend.db_system_name
    return await config.open_async(
        wrap=lambda driver: AsyncCaptureDriver(driver, system=system)
    )


@dataclass(frozen=True, slots=True)
class SnakeOrmConfig:
    """SnakeORM's ROOT config in ONE object: the connections (`databases`) and the panel settings.

    The user builds ONE, injects it into their app (Flask `app.config`, FastAPI `app.state`, ...)
    and out of it come the sessions (`open`), the panel config (`channels` / `debug_config`) and the
    migrations (`migrate`). Multi-DB by name in `databases`; `debug` are the channels
    (`"ssr,envelope,timing"`) and `advise_ms` the advisor threshold. `migrations_dir` decides WHERE
    the migrations live: a SINGLE directory (centralised) if declared, or `None` for the per-domain
    mode (one `migrations/` per domain). `language` fixes the language the panel OPENS in (default
    English; the user changes it with the 🌐 selector). The debug envelope
    (`snakeorm` in the JSON) is turned on by the `envelope` CHANNEL of `debug`, not by a separate
    flag. It is the FRIENDLY face: one object, everything inside, typed. SnakeORM reads THIS object,
    never the `.env`: each framework reads its environment its own way and fills this in.
    """

    databases: Mapping[str, SnakeConnectionConfig]
    debug: str = ""
    advise_ms: float = DEFAULT_MIN_MS
    migrations_dir: str | None = None
    language: SnakeDebugLanguage = SnakeDebugLanguage.EN
    production: bool | None = None
    """WHERE this app runs. Declaring it is what lets the risky channels be dropped.

    `None` means NOBODY SAID, which is a third state and not a synonym for development: while
    `debug` names no channel that hands out SQL it costs nothing, and the moment one is named the
    middleware refuses to start rather than guessing. This is the root config, so it is the one
    place a whole app answers the question once — and the reason it is a typed field rather than a
    key in a settings dict is the one `SnakeDebugConfig` gives: a dict returns `object` on every
    access and reintroduces the `Any` the thesis forbids.

    A Django app does not need it: that adapter reads `settings.DEBUG`, which is the framework's own
    answer to the same question.
    """

    def _connection(self, alias: str) -> SnakeConnectionConfig:
        """The connection that alias names, or a `SnakeError` saying which ones exist.

        It used to be `self.databases[alias]` bare, in two places. A `KeyError: 'analitycs'` does
        not say what aliases there are, does not say where they are declared, and is not even a
        `SnakeError` — so an application catching `SnakeError` around its start-up did not catch it.

        The answer already existed twelve lines below, in `_backend_for`, with "fail loud: a typo
        never falls back to a default" written on it. Three places, one question; now one answer.
        """
        try:
            return self.databases[alias]
        except KeyError:
            declared = ", ".join(sorted(self.databases)) or "(none)"
            raise SnakeConfigError(
                f"'{alias}' is not a connection of this config. The ones it declares are: "
                f"{declared}. A connection cannot be created from the command line: it has to be "
                f"in `databases`."
            ) from None

    def open(self, alias: str = "default") -> SnakeSession:
        """Open a session of the `alias` connection, with the captured driver (the panel sees the SQL)."""
        return open_session(self._connection(alias))

    def migrate(self, alias: str = "default") -> list[str]:
        """Apply the migrations to the `alias` connection. It returns the freshly applied ones.

        MULTI-ENGINE: driver and dialect come out of the `backend`, so it runs on
        SQLite/Postgres/MySQL alike (the CLI pairs them the same way). Idempotent. Two modes
        depending on `migrations_dir`:

        - A SINGLE directory (centralised): applied in its linear order.
        - `None` (PER DOMAIN): it discovers the `apps/*/migrations`, loads them ALL and orders them
          by FK DEPENDENCY (`accounts` creates `users` → it goes before `blog`, which references
          it). The order is DERIVED from the relations, not declared by hand.
        """
        from snakeorm.migration import (  # lazy: do not drag migration in if you do not migrate
            MigrationRunner,
            dependency_order,
            load,
        )

        # The alias is resolved FIRST. It used to be indexed at the end, so a typo in an argument
        # cost a full directory walk and a topological sort of every migration before failing —
        # and the failure was still a bare `KeyError`.
        connection = self._connection(alias)

        if self.migrations_dir is not None:
            pending = load(self.migrations_dir)
        else:
            import glob

            dirs = sorted(glob.glob("apps/*/migrations"))
            if not dirs:
                raise SnakeConfigError(
                    "Per-domain mode (`migrations_dir=None`): there are no migrations in `apps/*/migrations`. "
                    "Generate the ones for each domain (`makemigrations --only`) or declare a single directory."
                )
            pending = dependency_order([mig for d in dirs for mig in load(d)])

        driver, dialect = connection.driver_and_dialect()
        try:
            return MigrationRunner(driver, dialect).apply(pending)
        finally:
            driver.close()

    def channels(self) -> frozenset[SnakeDebugChannel]:
        """The panel channels (it parses `debug`; fail loud if a channel has a typo)."""
        return parse_channels(self.debug)

    def debug_config(self) -> SnakeDebugConfig:
        """The panel config: the advisor threshold, the language it opens in, and the environment."""
        return SnakeDebugConfig(
            advise_min_ms=self.advise_ms,
            language=self.language,
            production=self.production,
        )


class SnakeOrmDatabase(TypedDict):
    """The SHAPE of a `DATABASES["<alias>"]` SnakeORM understands (TypedDict = it types a dict literal).

    `ENGINE` accepts the short name (`"postgres"`) or Django's
    (`"django.db.backends.postgresql"`). The network pieces are optional (SQLite only uses `NAME`,
    which is the path of the file).
    """

    ENGINE: str
    NAME: str
    HOST: NotRequired[str]
    PORT: NotRequired[str]
    USER: NotRequired[str]
    PASSWORD: NotRequired[str]


class SnakeOrmSettings(TypedDict):
    """The SHAPE of the PANEL config constant (not the connection).

    `DEBUG` are the channels (`"ssr,envelope,timing"`; the `envelope` channel puts the debug in the
    JSON); `ADVISE_MS`, the index advisor threshold; `LANG` (`"es"`/`"en"`), the language the panel
    OPENS in. All optional: without `DEBUG` the panel stays off; without `ADVISE_MS`, the default
    threshold; without `LANG`, English.
    """

    DEBUG: NotRequired[str]
    ADVISE_MS: NotRequired[float]
    LANG: NotRequired[str]


# Accepted engine names → backend. It includes Django's so that its `DATABASES` changes nothing.
_ENGINES: dict[str, SnakeBackend] = {
    "postgres": SnakeBackend.POSTGRES,
    "postgresql": SnakeBackend.POSTGRES,
    "django.db.backends.postgresql": SnakeBackend.POSTGRES,
    "sqlite": SnakeBackend.SQLITE,
    "sqlite3": SnakeBackend.SQLITE,
    "django.db.backends.sqlite3": SnakeBackend.SQLITE,
    "mysql": SnakeBackend.MYSQL,
    "django.db.backends.mysql": SnakeBackend.MYSQL,
    # GeoDjango. On the wire PostGIS IS PostgreSQL, so the same driver and dialect serve it. This
    # opens the CONNECTION and nothing else: a geometry still reads as hex EWKB.
    "django.contrib.gis.db.backends.postgis": SnakeBackend.POSTGRES,
    "django.contrib.gis.db.backends.mysql": SnakeBackend.MYSQL,
    "django.contrib.gis.db.backends.spatialite": SnakeBackend.SQLITE,
}


def _backend_for(engine: str) -> SnakeBackend:
    """Resolve the `ENGINE` to the backend, or BLOW UP naming it (fail loud: a typo never falls back to a default)."""
    key = engine.strip().lower()
    try:
        return _ENGINES[key]
    except KeyError:
        valid = ", ".join(sorted({b.value for b in SnakeBackend}))
        raise SnakeConfigError(
            f"Unknown ENGINE: '{engine}'. SnakeORM accepts: {valid} "
            f"(or the 'django.db.backends.*' / 'django.contrib.gis.db.backends.*' equivalent)."
        ) from None


def connection_from_mapping(db: SnakeOrmDatabase) -> SnakeConnectionConfig:
    """Translate a connection dict (`DATABASES` format) into the centralised config."""
    return SnakeConnectionConfig(
        backend=_backend_for(db["ENGINE"]),
        name=str(db["NAME"]),
        host=db.get("HOST", "localhost"),
        port=db.get("PORT", ""),
        user=db.get("USER", ""),
        password=db.get("PASSWORD", ""),
    )


def debug_config_from_mapping(
    settings: SnakeOrmSettings,
) -> tuple[frozenset[SnakeDebugChannel], SnakeDebugConfig]:
    """Translate the panel config dict into (channels, config). Fail loud if anything is off.

    A channel with a typo or a non-numeric `ADVISE_MS` BLOW UP naming them: a panel that does not
    start —or a threshold that gets ignored— in silence is precisely the failure being fought.
    """
    channels = parse_channels(
        settings.get("DEBUG", "")
    )  # an unknown channel → SnakeConfigError
    raw = settings.get("ADVISE_MS", DEFAULT_MIN_MS)
    try:
        advise_min_ms = float(raw)
    except (TypeError, ValueError):
        raise SnakeConfigError(f"ADVISE_MS has to be a number, got {raw!r}.") from None
    return channels, SnakeDebugConfig(
        advise_min_ms=advise_min_ms,
        language=SnakeDebugLanguage.coerce(settings.get("LANG")),
    )
