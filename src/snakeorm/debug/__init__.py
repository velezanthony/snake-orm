"""DEBUG subsystem: it captures the SQL that runs and delivers it readable. A core that is AGNOSTIC of the web framework.

It captures the queries (a driver decorator + a per-scope collector), normalises them into a `DebugReport` and offers several renderers of that same report. The web adapters live in `snakeorm.contrib.*` and only CONSUME this.
"""

from snakeorm.debug.channel import DEBUG_ENV_KEY as DEBUG_ENV_KEY
from snakeorm.debug.config import PRODUCTION_ENV_KEY as PRODUCTION_ENV_KEY
from snakeorm.debug.channel import CHANNEL_AUDIENCE as CHANNEL_AUDIENCE
from snakeorm.debug.channel import ChannelAudience as ChannelAudience
from snakeorm.debug.channel import RISKY_CHANNELS as RISKY_CHANNELS
from snakeorm.debug.channel import (
    demand_every_channel_classified as demand_every_channel_classified,
)
from snakeorm.debug.channel import (
    UNIMPLEMENTED_CHANNELS as UNIMPLEMENTED_CHANNELS,
)
from snakeorm.debug.channel import SnakeDebugChannel as SnakeDebugChannel
from snakeorm.debug.channel import channels_from_env as channels_from_env
from snakeorm.debug.channel import parse_channels as parse_channels
from snakeorm.debug.config import ADVISE_MS_ENV_KEY as ADVISE_MS_ENV_KEY
from snakeorm.debug.config import LANG_ENV_KEY as LANG_ENV_KEY
from snakeorm.debug.config import SnakeDebugConfig as SnakeDebugConfig
from snakeorm.debug.config import SnakeDebugLanguage as SnakeDebugLanguage
from snakeorm.debug.matrix import SnakeWebFramework as SnakeWebFramework
from snakeorm.debug.matrix import channels_without_effect as channels_without_effect
from snakeorm.debug.matrix import warn_unimplemented as warn_unimplemented
from snakeorm.debug.matrix import warn_unsupported as warn_unsupported
from snakeorm.debug.testing import assert_queries as assert_queries
from snakeorm.debug.capture import AsyncCaptureDriver as AsyncCaptureDriver
from snakeorm.debug.capture import CaptureDriver as CaptureDriver
from snakeorm.debug.collector import DebugCollector as DebugCollector
from snakeorm.debug.collector import capture_queries as capture_queries
from snakeorm.debug.collector import current_collector as current_collector
from snakeorm.debug.html import render_report_html as render_report_html
from snakeorm.debug.html import render_report_page as render_report_page
from snakeorm.debug.record import QueryKind as QueryKind
from snakeorm.debug.record import QueryOrigin as QueryOrigin
from snakeorm.debug.record import QueryRecord as QueryRecord
from snakeorm.debug.report import DebugReport as DebugReport
from snakeorm.debug.report import DuplicateGroup as DuplicateGroup
from snakeorm.debug.report import RequestInfo as RequestInfo
from snakeorm.debug.otel import export_report as export_report
