# Security policy

## Reporting a vulnerability

If you find a security flaw in SnakeORM, **do not open a public issue**. Use GitHub's private
vulnerability reporting ("Report a vulnerability" on the repo's *Security* tab), which opens a
private channel with the maintainers.

Include, if you can: a description, the steps to reproduce it, the affected version and the impact
you believe it has. We try to answer within a reasonable time and we will keep you posted on the fix
and the disclosure.

## Security-driven design

Some of the project's decisions are defensive outright:

- **SQL is always parameterised.** Emission returns `(sql, params)` and the values are NEVER
  interpolated into the string; they travel as driver parameters. That shuts the door on SQL
  injection by construction, not by diligence.
- **Escaping in the debug tool.** The debug panel (`snakeorm.debug`) escapes every piece of SQL and
  every parameter it renders: a malicious value cannot turn into XSS.

## Warning: debug does NOT switch on in production

The debugging tool can expose SQL, parameters and database structure. The channels that reveal data
are **three** — `ssr`, `envelope` and `sidecar` — and all three are **dropped in production** even if
they are in the configuration: the environment gate overrules the config. On Django it is tied to
`settings.DEBUG`.

**`ssr` is the widest of the three**, and it is the one that reads as harmless. The other two hand
the SQL to whoever asked for it; `ssr` paints a panel into the page itself, with the parameter values
already substituted into the statement. An anonymous visitor gets the query and the data it was run
with.

The set is not a list kept by hand: every channel declares its audience in
`snakeorm.debug.channel`, and forgetting to classify one blows up at import. `ssr` was missing from
the risky set for a while — which is why this page names all three rather than counting them.

**Nothing is guessed about the environment.** Declare it with `SNAKE_ORM_PRODUCTION`, with
`production=` on the middleware, or in `SnakeDebugConfig`. If a risky channel is on and nothing has
declared the environment, the WSGI and ASGI middlewares **refuse to start** rather than pick a
default — defaulting to "development" would serve the panel in production, and defaulting to
"production" would silently switch off a tool somebody asked for.

A query panel served in production is attack surface handed over on a plate. Keep
`SNAKE_ORM_DEBUG` off (or without the risky channels) outside development.
