"""Two apps that each declare `through="Tagging"` over THEIR OWN bridge.

The class form of `through=` was fixed when the m2m bridge learned to take a class; the STRING form —
which is the usual one, because a bridge is normally declared after the model that crosses it — was
left resolving through `registry.table_by_name`, the index `register()` overwrites in silence.

Measured before the fix: both apps resolved to the SAME bridge, the one that registered last. Half
the application crosses through the wrong table, the SELECT comes out valid because the `via`/`to`
pair matches on both, and nothing says a word. It is bug #14 alive in the half the class fix did not
reach.

The import order at the bottom is part of the fixture: `archive` goes last so IT owns the name
"Tagging" in the by-name index, which is the arrangement that makes `catalogue` resolve wrong.
"""

from snakeorm.registry import SnakeRegistry

bridge_registry = SnakeRegistry()

from test.linker.bridge_by_name import catalogue as catalogue  # noqa: E402
from test.linker.bridge_by_name import archive as archive  # noqa: E402
