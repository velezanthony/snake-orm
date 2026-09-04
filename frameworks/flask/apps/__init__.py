"""Apps of the Flask demo: every package is a framework feature (here, `blog`).

The framework is a SHELL: the domain logic lives in `frameworks/shared/` (models, selectors and
services). Each app only re-exports that domain and exposes its Flask routes (a `Blueprint`).
"""
