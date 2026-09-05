"""SnakeORM's immutable metadata graph.

Frozen structures the Model Compiler produces ONCE; the runtime never re-inspects the class.
Re-exported with a redundant alias (`X as X`) instead of a string `__all__`: these are
IDENTIFIERS, so a rename drags them along and the checkers recognise it as an explicit
re-export.
"""

from snakeorm.metadata.check import SnakeCheckInfo as SnakeCheckInfo
from snakeorm.metadata.column import SnakeColumnInfo as SnakeColumnInfo
from snakeorm.metadata.enum_storage import SnakeEnumStorage as SnakeEnumStorage
from snakeorm.metadata.fk_action import SnakeFkAction as SnakeFkAction
from snakeorm.metadata.foreign_key import SnakeForeignKeyInfo as SnakeForeignKeyInfo
from snakeorm.metadata.index import SnakeIndexInfo as SnakeIndexInfo
from snakeorm.metadata.index_method import SnakeIndexMethod as SnakeIndexMethod
from snakeorm.metadata.int_size import SnakeIntSize as SnakeIntSize
from snakeorm.metadata.json_storage import SnakeJsonStorage as SnakeJsonStorage
from snakeorm.metadata.type_params import SnakeDateTimeParams as SnakeDateTimeParams
from snakeorm.metadata.type_params import SnakeFloatParams as SnakeFloatParams
from snakeorm.metadata.type_params import SnakeTimeParams as SnakeTimeParams
from snakeorm.metadata.type_params import SnakeDecimalParams as SnakeDecimalParams
from snakeorm.metadata.type_params import SnakeIntParams as SnakeIntParams
from snakeorm.metadata.type_params import SnakeJsonParams as SnakeJsonParams
from snakeorm.metadata.type_params import SnakeStrParams as SnakeStrParams
from snakeorm.metadata.type_params import SnakeTypeParams as SnakeTypeParams
from snakeorm.metadata.polymorphic import SnakePolymorphicInfo as SnakePolymorphicInfo
from snakeorm.metadata.primary_key import SnakePrimaryKeyInfo as SnakePrimaryKeyInfo
from snakeorm.metadata.relationship_kind import (
    SnakeRelationshipKind as SnakeRelationshipKind,
)
from snakeorm.metadata.relationship import (
    SnakeRelationshipInfo as SnakeRelationshipInfo,
)
from snakeorm.metadata.relationship import SnakeThroughInfo as SnakeThroughInfo
from snakeorm.metadata.routine import SnakeRoutineInfo as SnakeRoutineInfo
from snakeorm.metadata.server_default import SnakeServerDefault as SnakeServerDefault
from snakeorm.metadata.table import SnakeTableInfo as SnakeTableInfo
from snakeorm.metadata.table_kind import SnakeTableKind as SnakeTableKind
from snakeorm.metadata.trigger import SnakeTriggerEvent as SnakeTriggerEvent
from snakeorm.metadata.trigger import SnakeTriggerInfo as SnakeTriggerInfo
from snakeorm.metadata.trigger import SnakeTriggerTiming as SnakeTriggerTiming
