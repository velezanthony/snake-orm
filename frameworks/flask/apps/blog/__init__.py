"""`blog` app: a thin Flask shell over the SHARED domain (`frameworks/shared`).

No models, no queries and no rules live here: `models`, `selectors` and `services` re-export the
`shared` domain, and `urls` mounts a `Blueprint` with thin views that only parse, call the domain
with the request's session, and render/respond.
"""
