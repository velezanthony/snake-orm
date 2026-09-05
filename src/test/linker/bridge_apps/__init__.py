"""Two apps with a same-named BRIDGE model, in an isolated registry.

The m2m twin of `registry/collision_apps/`. `through=` took a string and the linker resolved it with
`model_by_name`, the index `register()` overwrites in silence — so with two `Tagging` classes in one
process the bridge frozen into `SnakeThroughInfo` was whichever registered last.

**The ORDER of the imports at the bottom is part of the fixture, not styling.** `archive` goes last
so IT wins the name "Tagging", which means the string form resolves to the wrong bridge for
`catalogue.Post`. With the opposite order the old code got it right by luck and a test written that
way would be green forever while watching nothing — the same trap `collision_apps` documents.
"""

from snakeorm.registry import SnakeRegistry

bridge_registry = SnakeRegistry()
"""Registry shared by the two test apps, isolated from the global one."""

from test.linker.bridge_apps import catalogue as catalogue  # noqa: E402
from test.linker.bridge_apps import archive as archive  # noqa: E402
