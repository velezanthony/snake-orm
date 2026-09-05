"""SnakeORM field descriptors and their field specifiers."""

from snakeorm.fields.check import snake_check as snake_check
from snakeorm.fields.check import snake_checks as snake_checks
from snakeorm.fields.check import snake_indexes as snake_indexes
from snakeorm.fields.column import MISSING as MISSING
from snakeorm.fields.column import SnakeColumn as SnakeColumn
from snakeorm.fields.column import snake_auto as snake_auto
from snakeorm.fields.column import snake_column as snake_column
from snakeorm.fields.column import snake_discriminator as snake_discriminator
from snakeorm.fields.enum import snake_enum as snake_enum
from snakeorm.fields.index import SnakeIndex as SnakeIndex
from snakeorm.fields.relationship import SnakeCollection as SnakeCollection
from snakeorm.fields.relationship import SnakePrefetch as SnakePrefetch
from snakeorm.fields.relationship import SnakePrefetchHop as SnakePrefetchHop
from snakeorm.core.exceptions import (
    SnakeRelationshipNotLoaded as SnakeRelationshipNotLoaded,
)
from snakeorm.fields.relationship import SnakePathProxy as SnakePathProxy
from snakeorm.fields.relationship import SnakeToMany as SnakeToMany
from snakeorm.fields.relationship import path_of as path_of
from snakeorm.fields.relationship import SnakeToOne as SnakeToOne
from snakeorm.fields.relationship import snake_to_many as snake_to_many
from snakeorm.fields.relationship import snake_to_many_through as snake_to_many_through
from snakeorm.fields.relationship import snake_to_one as snake_to_one
from snakeorm.fields.typed import snake_datetime as snake_datetime
from snakeorm.fields.typed import snake_datetimetz as snake_datetimetz
from snakeorm.fields.typed import snake_decimal as snake_decimal
from snakeorm.fields.typed import snake_int as snake_int
from snakeorm.fields.typed import snake_json as snake_json
from snakeorm.fields.typed import snake_str as snake_str
from snakeorm.fields.typed import snake_float as snake_float
from snakeorm.fields.typed import snake_time as snake_time
from snakeorm.fields.typed import snake_timetz as snake_timetz

# CANONICAL reference of the field specifiers. It CANNOT be passed to `@dataclass_transform`:
# PEP 681 demands a literal tuple at each site and mypy rejects it; the language imposes the
# duplication across the FIVE sites — `SnakeModel` and `SnakeView` in `model.py`, and the
# `@snake_model`, `@snake_view` and `@snake_db_first` decorators.
#
# `test/typing/test_field_specifiers.py` checks that they all match, and it DISCOVERS them through
# the `__dataclass_transform__` PEP 681 leaves at runtime instead of listing them: forgetting a
# site silently stops typing that path — with every test still green — so the count is exactly the
# thing that must not be remembered.
#
# The three relation specifiers ARE here, and NOT because relations are constructor arguments —
# they are not. `snake_to_one`, `snake_to_many` and `snake_to_many_through` each declare
# `init: Literal[False]`, and a checker only reads that signal off a call it recognises as a field
# specifier, i.e. one listed here. Leaving one out makes the checker read it as "a field with a
# default" and bless a line the runtime rejects with `TypeError`.
SNAKE_FIELD_SPECIFIERS = (
    snake_column,
    snake_auto,
    snake_enum,
    snake_int,
    snake_str,
    snake_decimal,
    snake_datetime,
    snake_datetimetz,
    snake_float,
    snake_time,
    snake_timetz,
    snake_json,
    snake_to_one,
    snake_to_many,
    snake_to_many_through,
    snake_discriminator,
)
