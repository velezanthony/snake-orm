"""Domain USE CASES (each action's functionality, written once), one module per domain."""

from shared.usecases.blog_usecases import Failure as Failure
from shared.usecases.blog_usecases import create_post as create_post
from shared.usecases.blog_usecases import edit_post as edit_post
from shared.usecases.blog_usecases import editable_post as editable_post
from shared.usecases.blog_usecases import list_posts as list_posts
from shared.usecases.blog_usecases import list_published as list_published
from shared.usecases.blog_usecases import list_user_posts as list_user_posts
from shared.usecases.blog_usecases import login as login
from shared.usecases.blog_usecases import register as register
from shared.usecases.blog_usecases import remove_post as remove_post
from shared.usecases.blog_usecases import show_post as show_post
from shared.usecases.blog_usecases import user_stats as user_stats
