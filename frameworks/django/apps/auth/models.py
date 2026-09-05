"""Models of the auth domain: re-exports the ones from the SHARED package (`shared.models`).

The framework declares NO models of its own; the metadata graph lives once in `shared` and here it
is only re-exposed (from the package, so that `snake_link()` has already linked the whole graph).
"""

from __future__ import annotations

from shared.models import ApiToken as ApiToken
from shared.models import LoginSession as LoginSession
