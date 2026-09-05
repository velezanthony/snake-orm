"""Models of the accounts domain: it re-exports those of the SHARED package (`shared.models`).

The framework does NOT declare models of its own; the metadata graph lives once in `shared` and is
only re-exposed here (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import User as User
from shared.models import Role as Role
from shared.models import UserRole as UserRole
from shared.models import UserStats as UserStats
