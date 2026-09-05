"""Two "apps" with a model of the same name, in an ISOLATED registry.

Reproduces the real scenario of BUG #14 —`billing.Customer` and `crm.Customer`— with actual
modules and not with classes defined inside a function: the compiler resolves the annotations with
`get_type_hints`, which looks at the MODULE globals, so a local class would not resolve and the
test would fail for a reason other than the one it claims to check.

The registry is its own so as not to pollute the global one: a second `Customer` in there steals the
relations from the other tests, which is exactly how this bug was discovered.

**The ORDER of the imports below is part of the test, not a styling detail.** The index by class
name is kept by the LAST one to register, so by importing `billing` first and `crm` afterwards,
`crm.Customer` wins the name "Customer" — and that is precisely the order in which the old code
emitted the billing FK pointing at the CRM table. With the opposite order it got it right by sheer
luck, and a test written that way would have gone green forever while watching nothing.
"""

from snakeorm.registry import SnakeRegistry

apps_registry = SnakeRegistry()
"""Registry shared by the two test apps, isolated from the global one."""

# Deliberate order (see the docstring): billing first, CRM afterwards.
from test.registry.collision_apps import billing as billing  # noqa: E402
from test.registry.collision_apps import crm as crm  # noqa: E402
