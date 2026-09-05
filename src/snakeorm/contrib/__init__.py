"""Optional web adapters: they CONSUME the `snakeorm.debug` kernel, they do not define it (a thin edge, hexagonal architecture).

None of them imports its framework at module level, so they import and test without FastAPI/Flask/Django installed.
"""

from snakeorm.contrib.asgi import SnakeDebugASGI as SnakeDebugASGI
from snakeorm.contrib.config import SnakeOrmConfig as SnakeOrmConfig
from snakeorm.debug import SnakeDebugLanguage as SnakeDebugLanguage
from snakeorm.contrib.config import SnakeOrmSettings as SnakeOrmSettings
from snakeorm.contrib.config import (
    debug_config_from_mapping as debug_config_from_mapping,
)
from snakeorm.contrib.config import open_session as open_session
from snakeorm.contrib.config import open_session_async as open_session_async
from snakeorm.contrib.django import SnakeDebugMiddleware as SnakeDebugMiddleware
from snakeorm.contrib.sidecar import SidecarBuffer as SidecarBuffer
from snakeorm.contrib.wsgi import SnakeDebugWSGI as SnakeDebugWSGI
