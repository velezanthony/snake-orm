"""Services (writes/rules) of the blog domain: it re-exports those of `shared.services.blog_services`.

They mutate state (create/update/delete) or validate it (authenticate), taking the request's
`SnakeSession`. Post ownership (only its author edits/deletes it) is checked in `shared`, not here.
"""

from shared.services.blog_services import authenticate as authenticate
from shared.services.blog_services import create_post as create_post
from shared.services.blog_services import delete_post as delete_post
from shared.services.blog_services import register_user as register_user
from shared.services.blog_services import update_post as update_post
