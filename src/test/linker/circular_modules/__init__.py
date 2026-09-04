"""Two modules whose models point at each other, with NO runtime import between them.

This is the layout `TYPE_CHECKING` exists for, and the one the ORM could not link. Each module
imports the other's model INSIDE the block, so at runtime the name is nowhere: `get_type_hints`
raises `NameError` and the linker died on a message that names a type nobody wrote by hand.

The registry is here so both modules share one and neither imports the other to get it.
"""

from __future__ import annotations

from snakeorm.registry import SnakeRegistry

circular_registry = SnakeRegistry()
