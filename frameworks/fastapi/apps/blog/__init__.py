"""`blog` app of the FastAPI shell.

A thin shell over the domain in `shared/`: `models`, `selectors` and `services` are DUMB re-exports
of the single source of truth; `urls` mounts the `APIRouter` with thin endpoints that only parse,
call the domain and answer JSON.
"""
