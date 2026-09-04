"""DUMB Django shell: re-exports the domain's SERVICES (writes), which live in `shared`.

Every service takes a `SnakeSession` and mutates state (or validates it). A post's OWNERSHIP (only
its author edits or deletes it) is checked INSIDE the service, not in the view. The logic is defined
ONCE in `shared.services.blog_services` and is shared across the three frameworks.
"""

from __future__ import annotations

from shared.services.blog_services import authenticate as authenticate
from shared.services.blog_services import create_post as create_post
from shared.services.blog_services import delete_post as delete_post
from shared.services.blog_services import register_user as register_user
from shared.services.blog_services import update_post as update_post
