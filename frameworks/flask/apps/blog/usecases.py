"""Use cases (the functionality of each action) of the blog domain: re-exports those of `shared.usecases`.

The whole OPERATION -validate, orchestrate services/selectors and confirm (`commit`)- lives only
once in `shared.usecases.blog_usecases`. Here they are only re-exposed so that the views can call
them with flat parameters and translate their result (data or `Failure`) into the HTTP response.
"""

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
