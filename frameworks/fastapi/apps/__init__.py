"""Apps of the FastAPI shell: one package per domain (today, `blog`).

The framework is DUMB: every app re-exports the domain from `shared/` and only contributes the
framework glue (router, request schemas, serialization). The business logic does NOT live here.
"""
