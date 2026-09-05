"""SnakeORM — a dataclass-first, type-first ORM for Python 3.11+.

This module is the PUBLIC SURFACE: everything needed to declare a model, query it and execute it
is imported from here, without knowing the package's internal structure.

    from snakeorm import SnakeColumn, snake_auto, snake_model, snake_str

    @snake_model
    class User:
        id: SnakeColumn[int] = snake_auto()
        email: SnakeColumn[str] = snake_str(unique=True)

What is NOT here, on purpose: the migration operations (`CreateTable`, `AddColumn`...) and the
structures of the compiled graph (`SnakeTableInfo`, `SnakeColumnInfo`...). They live in
`snakeorm.migration` and `snakeorm.metadata`, which is where the generated migration files import
them from. Duplicating them here would publish two paths to the same thing.
"""

from importlib import metadata as _metadata

from snakeorm.decorators import SnakeResult as SnakeResult
from snakeorm.decorators import SnakeRow as SnakeRow
from snakeorm.decorators import snake_abstract as snake_abstract
from snakeorm.decorators import snake_db_first as snake_db_first
from snakeorm.decorators import snake_function as snake_function
from snakeorm.decorators import snake_model as snake_model
from snakeorm.decorators import snake_result as snake_result
from snakeorm.decorators import snake_row as snake_row
from snakeorm.decorators import snake_table as snake_table
from snakeorm.decorators import snake_trigger as snake_trigger
from snakeorm.decorators import snake_view as snake_view
from snakeorm.dialects import MySQLDialect as MySQLDialect
from snakeorm.dialects import PostgresDialect as PostgresDialect
from snakeorm.dialects import SnakeDialect as SnakeDialect
from snakeorm.dialects import SQLiteDialect as SQLiteDialect
from snakeorm.core.converters import register_converter as register_converter
from snakeorm.drivers import AsyncDriver as AsyncDriver
from snakeorm.drivers import AsyncLoggingDriver as AsyncLoggingDriver
from snakeorm.drivers import AsyncPsycopgDriver as AsyncPsycopgDriver
from snakeorm.drivers import AsyncPyMySQLDriver as AsyncPyMySQLDriver
from snakeorm.drivers import AsyncSQLiteDriver as AsyncSQLiteDriver
from snakeorm.drivers import AsyncSnakePool as AsyncSnakePool
from snakeorm.drivers import AsyncTimeoutDriver as AsyncTimeoutDriver
from snakeorm.drivers import LoggingDriver as LoggingDriver
from snakeorm.drivers import PsycopgDriver as PsycopgDriver
from snakeorm.drivers import PyMySQLDriver as PyMySQLDriver
from snakeorm.drivers import SnakeDriver as SnakeDriver
from snakeorm.drivers import SnakePool as SnakePool
from snakeorm.drivers import SQLiteDriver as SQLiteDriver
from snakeorm.drivers import TimeoutDriver as TimeoutDriver
from snakeorm.drivers import psycopg_pool as psycopg_pool
from snakeorm.core.exceptions import SnakeAggregateNotLoaded as SnakeAggregateNotLoaded
from snakeorm.core.exceptions import SnakeColumnNotLoaded as SnakeColumnNotLoaded
from snakeorm.core.exceptions import SnakeConfigError as SnakeConfigError
from snakeorm.core.exceptions import SnakeDialectError as SnakeDialectError
from snakeorm.core.exceptions import SnakeEmitError as SnakeEmitError
from snakeorm.core.exceptions import SnakeError as SnakeError
from snakeorm.core.exceptions import SnakeMigrationError as SnakeMigrationError
from snakeorm.core.exceptions import (
    SnakeModelDefinitionError as SnakeModelDefinitionError,
)
from snakeorm.core.exceptions import SnakeModelError as SnakeModelError
from snakeorm.core.exceptions import SnakeNodeError as SnakeNodeError
from snakeorm.core.exceptions import SnakeCheckViolation as SnakeCheckViolation
from snakeorm.core.exceptions import (
    SnakeForeignKeyViolation as SnakeForeignKeyViolation,
)
from snakeorm.core.exceptions import SnakeIntegrityError as SnakeIntegrityError
from snakeorm.core.exceptions import SnakeNotNullViolation as SnakeNotNullViolation
from snakeorm.core.exceptions import SnakePoolTimeout as SnakePoolTimeout
from snakeorm.core.exceptions import SnakeUniqueViolation as SnakeUniqueViolation
from snakeorm.core.exceptions import SnakeRegistryError as SnakeRegistryError
from snakeorm.core.exceptions import (
    SnakeRelationshipNotLoaded as SnakeRelationshipNotLoaded,
)
from snakeorm.core.exceptions import SnakeUnknownColumn as SnakeUnknownColumn
from snakeorm.core.exceptions import (
    SnakeUnknownRelationship as SnakeUnknownRelationship,
)
from snakeorm.core.exceptions import (
    SnakeUnlinkedRelationship as SnakeUnlinkedRelationship,
)
from snakeorm.core.exceptions import SnakeUnsupportedFeature as SnakeUnsupportedFeature
from snakeorm.core.exceptions import SnakeValueError as SnakeValueError
from snakeorm.core.exceptions import SnakeWarning as SnakeWarning
from snakeorm.expressions import SnakeCast as SnakeCast
from snakeorm.expressions import SnakeCase as SnakeCase
from snakeorm.expressions import SnakeCoalesce as SnakeCoalesce
from snakeorm.expressions import SnakeCondition as SnakeCondition
from snakeorm.expressions import SnakeSubquery as SnakeSubquery
from snakeorm.expressions import SnakeExpr as SnakeExpr
from snakeorm.expressions import SnakeFunc as SnakeFunc
from snakeorm.expressions import SnakeNullIf as SnakeNullIf
from snakeorm.expressions import SnakeOrder as SnakeOrder
from snakeorm.expressions import SnakeValue as SnakeValue
from snakeorm.expressions import SnakeKey as SnakeKey
from snakeorm.expressions import SnakeKeys as SnakeKeys
from snakeorm.expressions import SnakeWindow as SnakeWindow
from snakeorm.expressions import snake_key as snake_key
from snakeorm.expressions import snake_keys as snake_keys
from snakeorm.expressions import avg as avg
from snakeorm.expressions import count as count
from snakeorm.expressions import dense_rank as dense_rank
from snakeorm.expressions import lag as lag
from snakeorm.expressions import lead as lead
from snakeorm.expressions import max_ as max_
from snakeorm.expressions import min_ as min_
from snakeorm.expressions import rank as rank
from snakeorm.expressions import row_number as row_number
from snakeorm.expressions import SnakeStringAgg as SnakeStringAgg
from snakeorm.expressions import string_agg as string_agg
from snakeorm.expressions import snake_case as snake_case
from snakeorm.expressions import snake_cast as snake_cast
from snakeorm.expressions import snake_substring as snake_substring
from snakeorm.expressions import snake_replace as snake_replace
from snakeorm.expressions import snake_ceil as snake_ceil
from snakeorm.expressions import snake_floor as snake_floor
from snakeorm.expressions import snake_sqrt as snake_sqrt
from snakeorm.expressions import snake_power as snake_power
from snakeorm.expressions import snake_lower as snake_lower
from snakeorm.expressions import snake_upper as snake_upper
from snakeorm.expressions import snake_trim as snake_trim
from snakeorm.expressions import snake_length as snake_length
from snakeorm.expressions import snake_concat as snake_concat
from snakeorm.expressions import snake_date_trunc as snake_date_trunc
from snakeorm.expressions import snake_extract as snake_extract
from snakeorm.expressions import snake_abs as snake_abs
from snakeorm.expressions import snake_round as snake_round

# The unit a date is shifted by. It is exported because `snake_date_add` NAMES it in its
# signature: a caller who can reach the function and not its argument type cannot annotate what
# they are passing, which is the gap `test_public_api` exists to close.
from snakeorm.expressions import SnakeDatePart as SnakeDatePart
from snakeorm.expressions import snake_date_add as snake_date_add
from snakeorm.expressions import snake_date_sub as snake_date_sub
from snakeorm.expressions import SNAKE_CURRENT_ROW as SNAKE_CURRENT_ROW
from snakeorm.expressions import SnakeFrame as SnakeFrame
from snakeorm.expressions import SnakeFrameBound as SnakeFrameBound
from snakeorm.expressions import SnakeFrameMode as SnakeFrameMode
from snakeorm.expressions import snake_following as snake_following
from snakeorm.expressions import snake_preceding as snake_preceding
from snakeorm.expressions import snake_range as snake_range
from snakeorm.expressions import snake_rows as snake_rows
from snakeorm.expressions import snake_coalesce as snake_coalesce
from snakeorm.expressions import snake_nullif as snake_nullif
from snakeorm.expressions import sum_ as sum_
from snakeorm.fields import SnakeCollection as SnakeCollection
from snakeorm.fields import SnakeColumn as SnakeColumn
from snakeorm.fields import SnakeIndex as SnakeIndex
from snakeorm.fields import SnakePrefetch as SnakePrefetch
from snakeorm.fields import SnakePrefetchHop as SnakePrefetchHop
from snakeorm.fields import SnakeToMany as SnakeToMany
from snakeorm.fields import SnakeToOne as SnakeToOne
from snakeorm.fields import snake_auto as snake_auto
from snakeorm.fields import snake_check as snake_check
from snakeorm.fields import snake_checks as snake_checks
from snakeorm.fields import snake_column as snake_column
from snakeorm.fields import snake_datetime as snake_datetime
from snakeorm.fields import snake_datetimetz as snake_datetimetz
from snakeorm.fields import snake_decimal as snake_decimal
from snakeorm.fields import snake_discriminator as snake_discriminator
from snakeorm.fields import snake_enum as snake_enum
from snakeorm.fields import snake_indexes as snake_indexes
from snakeorm.fields import snake_int as snake_int
from snakeorm.fields import snake_json as snake_json
from snakeorm.fields import snake_str as snake_str
from snakeorm.fields import snake_float as snake_float
from snakeorm.fields import snake_time as snake_time
from snakeorm.fields import snake_timetz as snake_timetz
from snakeorm.fields import snake_to_many as snake_to_many
from snakeorm.fields import snake_to_many_through as snake_to_many_through
from snakeorm.fields import snake_to_one as snake_to_one
from snakeorm.linker import snake_link as snake_link
from snakeorm.metadata import SnakeCheckInfo as SnakeCheckInfo
from snakeorm.metadata import SnakeEnumStorage as SnakeEnumStorage
from snakeorm.metadata import SnakeFkAction as SnakeFkAction
from snakeorm.metadata import SnakeIntSize as SnakeIntSize
from snakeorm.metadata import SnakeIndexMethod as SnakeIndexMethod
from snakeorm.metadata import SnakeJsonStorage as SnakeJsonStorage
from snakeorm.metadata import SnakeRelationshipKind as SnakeRelationshipKind
from snakeorm.metadata import SnakeServerDefault as SnakeServerDefault
from snakeorm.metadata import SnakeThroughInfo as SnakeThroughInfo
from snakeorm.metadata import SnakeDateTimeParams as SnakeDateTimeParams
from snakeorm.metadata import SnakeDecimalParams as SnakeDecimalParams
from snakeorm.metadata import SnakeFloatParams as SnakeFloatParams
from snakeorm.metadata import SnakeIntParams as SnakeIntParams
from snakeorm.metadata import SnakeJsonParams as SnakeJsonParams
from snakeorm.metadata import SnakeStrParams as SnakeStrParams
from snakeorm.metadata import SnakeTimeParams as SnakeTimeParams
from snakeorm.metadata import SnakeTriggerEvent as SnakeTriggerEvent
from snakeorm.metadata import SnakeTriggerInfo as SnakeTriggerInfo
from snakeorm.metadata import SnakeTriggerTiming as SnakeTriggerTiming
from snakeorm.model import SnakeModel as SnakeModel
from snakeorm.model import SnakeView as SnakeView
from snakeorm.query import SnakeCompound as SnakeCompound
from snakeorm.query import SnakeJoin as SnakeJoin
from snakeorm.query import SnakeJoinedQuery as SnakeJoinedQuery
from snakeorm.query import SnakeQuery as SnakeQuery
from snakeorm.query import SnakeRecursive as SnakeRecursive
from snakeorm.query import SnakeSetOp as SnakeSetOp
from snakeorm.registry import registry as registry
from snakeorm.session import AsyncSession as AsyncSession
from snakeorm.session import SnakeIsolation as SnakeIsolation
from snakeorm.connection import SnakeBackend as SnakeBackend
from snakeorm.connection import SnakeConnectionConfig as SnakeConnectionConfig
from snakeorm.session import SnakeSession as SnakeSession
from snakeorm.times import SnakeUtc as SnakeUtc
from snakeorm.times import parse_utc as parse_utc
from snakeorm.times import to_utc as to_utc
from snakeorm.times import utc_from_zone as utc_from_zone
from snakeorm.times import utc_now as utc_now
from snakeorm.session import is_transient as is_transient
from snakeorm.session import snake_session as snake_session
from snakeorm.session import with_retry as with_retry
from snakeorm.core.signals import SnakeSignal as SnakeSignal
from snakeorm.core.signals import snake_on as snake_on

__version__ = _metadata.version("snake-orm")
"""The installed version, READ from the metadata and not written down a second time.

Two copies of one number agree until the release somebody bumps one of them, and a bug report
against the wrong version sends everybody to read the wrong code.
"""
