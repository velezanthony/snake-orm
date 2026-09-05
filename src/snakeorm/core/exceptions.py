"""Public exception hierarchy: every ORM error hangs off `SnakeError`.

Each one ALSO inherits from the builtin it replaces (ValueError/TypeError/...) for compatibility:
`except SnakeError` gains precision and `except ValueError` keeps working. Multiple inheritance,
deliberately. The `TypeError`s from the generated `__init__` (calling a callable wrong) do NOT live
here.
"""

from __future__ import annotations


class SnakeError(Exception):
    """Root of every SnakeORM error."""


class SnakeModelError(SnakeError, TypeError):
    """Something without `@snake_model` was passed as a model: the type is inappropriate."""


class SnakeModelDefinitionError(SnakeError, ValueError):
    """The model carries `@snake_model` but is declared wrong (with no PK, for instance).

    It is a valid class with invalid content: hence `ValueError` and not `TypeError`.
    """


class SnakeRegistryError(SnakeError, ValueError):
    """Trouble in the registry: unregistered model or table collision."""


class SnakeUnknownRelationship(SnakeError, ValueError):
    """A relation the table does not declare was named."""


class SnakeUnlinkedRelationship(SnakeError, RuntimeError):
    """A relation was used before calling `snake_link()`."""


class SnakeRelationshipNotLoaded(SnakeError, AttributeError):
    """A relation the query did not load was accessed (the anti-N+1 lock)."""


class SnakeAggregateNotLoaded(SnakeError, AttributeError):
    """An aggregate asked for through the escape hatch (`obj.aggregate.x`) was not loaded (a missing
    `annotate`, or a missing name)."""


class SnakeColumnNotLoaded(SnakeError, AttributeError):
    """A column left out by `only()`/`defer()` was read on the instance.

    The sibling of `SnakeRelationshipNotLoaded`, and it exists for the same reason: the alternative
    is the descriptor falling through to the column's DEFAULT, which hands back `None` or `0` for a
    value nobody loaded. A wrong answer with no error is the one outcome this ORM does not produce.
    """


class SnakeUnknownColumn(SnakeError, ValueError):
    """A column the table does not declare was named."""


class SnakeConfigError(SnakeError, ValueError):
    """Configuration is missing to operate (e.g. there is no way to determine the DSN)."""


class SnakePoolTimeout(SnakeError, TimeoutError):
    """The pool could not hand over a healthy connection within the deadline.

    It has a name of its own because the engine's raw error ("connection pool exhausted") does not
    tell apart two situations that call for opposite actions: "there is no slot right now" (wait, or
    raise the pool size) and "I have spent thirty seconds failing to get a live one" (the database
    is down). It inherits from `TimeoutError` so a generic retry treats it as what it is.
    """


class SnakeIntegrityError(SnakeError):
    """A constraint refused the write. ONE exception where the three drivers raised three.

    A duplicate key came back as `psycopg2.errors.UniqueViolation`, `pymysql.err.IntegrityError` and
    `sqlite3.IntegrityError`, so the `except` handling it was the one part of an application that
    could not be moved between engines.

    The driver's exception is CHAINED, never swallowed: it stays in `__cause__` and the traceback
    prints both. Whoever catches gets a portable name, whoever debugs still gets the server's own
    words.

    Catch this one to be coarse, or a subtype below to be precise. Every engine says which
    constraint broke, so the subtype is read off a CODE and never off the message: reading text is
    how a detector fails open.

    It KEEPS what it was built from, in `driver_error` and `code`, so the classification is testable
    without an engine — checking that MariaDB's 4025 lands in `SnakeCheckViolation` needs no
    MariaDB, while `__cause__` proves the chaining and says nothing about the DECISION. The engine
    tests then check the other half, that the engine really does send that code.
    """

    def __init__(
        self,
        message: str,
        *,
        driver_error: BaseException | None = None,
        code: str | int | None = None,
    ) -> None:
        super().__init__(message)
        self.driver_error = driver_error
        """The exception the DBAPI raised, kept whole. Also reachable as `__cause__`."""
        self.code = code
        """The engine's own code that decided the subtype: a SQLSTATE, a MySQL errno or an SQLite
        extended-result name. What was READ, not what was guessed — so a wrong classification can be
        argued with rather than re-derived."""


class SnakeUniqueViolation(SnakeIntegrityError):
    """A UNIQUE constraint or a primary key already holds that value."""


class SnakeForeignKeyViolation(SnakeIntegrityError):
    """A foreign key points at a row that is not there, or a referenced row was removed."""


class SnakeNotNullViolation(SnakeIntegrityError):
    """A NOT NULL column was given nothing.

    Rare from a typed model —`SnakeColumn[int]` refuses a `None` long before any driver sees it— and
    that is exactly why it is here: it arrives from what the type system does not cover, such as raw
    SQL or a column a migration added.
    """


class SnakeCheckViolation(SnakeIntegrityError):
    """A CHECK constraint said no.

    The one that proves the classification cannot key on the driver's exception CLASS: MySQL raises
    `OperationalError` for this and `IntegrityError` for the other three.
    """


class SnakeUnsupportedFeature(SnakeError, ValueError):
    """The combination asked for exists in the design but is not built yet."""


class SnakeDialectError(SnakeError, ValueError):
    """The dialect does not know how to translate something (a Python type, a SQL literal)."""


class SnakeMigrationError(SnakeError, ValueError):
    """Trouble with the migration history on disk: duplicated numbering, gaps, a file that does not
    expose `migration`, or a migration that fails while being applied without transactional DDL
    (leaving the DB half done)."""


class SnakeEmitError(SnakeError, ValueError):
    """Valid SQL cannot be emitted from what was given (an INSERT with no columns...)."""


class SnakeNodeError(SnakeError, TypeError):
    """The emitter received an AST node it does not know how to translate into SQL."""


class SnakeValueError(SnakeError, ValueError):
    """A value does not fit its declared column (e.g. a `Decimal` with more decimals than the
    `scale`). Raised on WRITE, before touching the DB, so the engine does not round it or store it
    half-way silently."""


class SnakeDtoError(SnakeError, ValueError):
    """A generated DTO cannot be honoured: its declaration is contradictory, it names a column the
    model does not have, or the file it has to be written into holds something the generator does
    not manage. It is raised at DECLARATION time whenever it can be, so the mistake dies where it
    was written and never becomes a body that quietly lost a column."""


class SnakeWarning(UserWarning):
    """An ORM warning that does not stop you, but is worth seeing: a bulk write that fires no
    signals, or an engine with less fidelity than another. It inherits from `UserWarning` so that
    `filterwarnings("ignore", category=SnakeWarning)` silences ONLY the ORM's."""
