# Errors and warnings

This ORM **shouts**: it does not fix things behind your back and it does not
degrade in silence. Every exception below marks a decision someone has to make, and its message says
what to write instead — not just what went wrong.

`SnakeWarning` is a `UserWarning` of its own so that
`filterwarnings("ignore", category=SnakeWarning)` silences the ORM and nothing else.

!!! note "Where this text comes from"

    Everything below the headings is generated from the package's own docstrings, on every build.

## Base

::: snakeorm.core.exceptions.SnakeError

## Declaration

::: snakeorm.core.exceptions.SnakeModelError

::: snakeorm.core.exceptions.SnakeModelDefinitionError

::: snakeorm.core.exceptions.SnakeRegistryError

::: snakeorm.core.exceptions.SnakeDtoError

::: snakeorm.core.exceptions.SnakeUnknownColumn

::: snakeorm.core.exceptions.SnakeUnknownRelationship

::: snakeorm.core.exceptions.SnakeUnlinkedRelationship

## Execution

::: snakeorm.core.exceptions.SnakeValueError

::: snakeorm.core.exceptions.SnakeEmitError
::: snakeorm.core.exceptions.SnakeNodeError

::: snakeorm.core.exceptions.SnakeRelationshipNotLoaded

::: snakeorm.core.exceptions.SnakeAggregateNotLoaded

::: snakeorm.core.exceptions.SnakeColumnNotLoaded

::: snakeorm.core.exceptions.SnakeUnsupportedFeature

## Constraints

A constraint that refuses a write raises the SAME exception on the three engines. Each one is classified from the code the engine sends — a SQLSTATE, a MySQL errno or an SQLite extended result name — never from the message, and never from the driver's exception class: on MySQL a CHECK arrives as `OperationalError` and the other three as `IntegrityError`.

The driver's exception is chained, not hidden. It stays in `__cause__` and, spelled out, in `driver_error`; `code` says which code decided the subtype.

```python
from snakeorm import SnakeIntegrityError, SnakeUniqueViolation

try:
    session.add(User(email="taken@example.com"))
    session.commit()
except SnakeUniqueViolation as refused:
    # the same exception on PostgreSQL, MySQL and SQLite
    print(refused.code)          # "23505" | 1062 | "SQLITE_CONSTRAINT_UNIQUE"
    print(refused.driver_error)  # the DBAPI's own, also in __cause__
except SnakeIntegrityError:
    # the coarse catch: any constraint at all
    session.rollback()
```

::: snakeorm.core.exceptions.SnakeIntegrityError

::: snakeorm.core.exceptions.SnakeUniqueViolation

::: snakeorm.core.exceptions.SnakeForeignKeyViolation

::: snakeorm.core.exceptions.SnakeNotNullViolation

::: snakeorm.core.exceptions.SnakeCheckViolation

## Engine and migrations

::: snakeorm.core.exceptions.SnakeDialectError

::: snakeorm.core.exceptions.SnakeMigrationError

::: snakeorm.core.exceptions.SnakeConfigError

::: snakeorm.core.exceptions.SnakePoolTimeout

## Warnings

::: snakeorm.core.exceptions.SnakeWarning

