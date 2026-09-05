"""Capturing the ORIGIN of a query: the USER code frame that fired it.

The idea is the Django Debug Toolbar one: when listing a query, say WHICH file and line it came
from, so you can find the code that fires the extra calls. The stack is walked from here upwards
and the frames internal to the `snakeorm` package are SKIPPED (the same way DDT skips the
framework's); the first frame that is not the ORM's is the origin.

`sys._getframe` is used (not `traceback.extract_stack`) on purpose: only `co_filename`, `f_lineno`
and `co_name` are read off each frame, without touching the disk to read the source code. That way
the cost per captured query is minimal (and it is only paid when a capture scope is active).
"""

from __future__ import annotations

import os
import sys
from types import FrameType

from snakeorm.debug.record import QueryOrigin

# Root of the `snakeorm` package on disk: a frame is INTERNAL if its file hangs off here.
# `origin.py` lives in `snakeorm/debug/`, so going up two levels gives `.../snakeorm`.
_SNAKEORM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def capture_origin() -> QueryOrigin | None:
    """The first USER code frame above the call, or `None` if there is none.

    It walks the stack upwards skipping every frame whose file hangs off the `snakeorm` package
    (this function, the collector, the capture driver, the session, the compiler…). The first one
    that is not the ORM's is who really fired the query.
    """
    frame: FrameType | None = sys._getframe()
    while frame is not None:
        code = frame.f_code
        filename = os.path.abspath(code.co_filename)
        if not filename.startswith(_SNAKEORM_DIR):
            return QueryOrigin(
                file=code.co_filename, line=frame.f_lineno, function=code.co_name
            )
        frame = frame.f_back
    return None
