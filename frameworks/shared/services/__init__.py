"""Domain SERVICES (writes/logic), one module per domain. Re-exported so imports stay flat."""

from shared.services.blog_services import authenticate as authenticate
from shared.services.blog_services import create_post as create_post
from shared.services.blog_services import delete_post as delete_post
from shared.services.blog_services import register_user as register_user
from shared.services.blog_services import update_post as update_post
