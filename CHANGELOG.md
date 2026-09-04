# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

**No dates yet, and that is the convention rather than an omission.** `Unreleased` carries no date
because the date is what a release stamps on it. The repository holds no tag, the package is not on
PyPI, and `docs/contributors/release.md` says what the first release would still take. When the first
tag lands, this section gets a heading with its version and its day, and a new `Unreleased` opens
above it.

**One language, and it is English.** The prose under `docs/` is mirrored in Spanish because it
teaches; this file records what changed, and it is read beside a tag and a package page — the same
audience the code, the docstrings and every message the ORM emits already speak to.

**What this is not.** Not a list of commits. What survived here is what changed for somebody USING
the ORM: the defects that produced wrong data or wrong SQL, and the reversals of decisions already
made. Ordered by weight inside each group, because that is how somebody reads a changelog they have
never seen before.

## Unreleased

### Security

**Remote code execution in the scaffolder.** `scaffold create` reads table names, column names and
comments FROM THE DATABASE and writes them into a `models.py` the user imports; they went in raw
through f-strings. Confirmed with a real payload: a `COMMENT ON COLUMN` that closes the
`db_comment="..."`, puts an `__import__(...).system(...)` on its line and reopens a literal. The file
compiled and ran the command on import — whoever controlled a legacy schema controlled the machine of
whoever scaffolded it. The migration renderer was already escaping the same field correctly.

### Fixed — wrong data

**A JOIN resolved by CLASS NAME and went to the wrong table.** Two models with the same class name in
different modules resolved to whichever the global index happened to hold. The query ran and returned
rows. It took three passes to close: first a foreign key pointing at another model's table, then a
`through=` chain that still went to the global index, and finally the relationship resolution itself.
A class name does not identify a model.

**A `NULL` in a column with a converter became `False`, and was persisted.**

**A UNION with narrowed branches put values in the wrong field.** SQLite REGROUPED a compound's
operators and nobody noticed, and a compound's `ORDER BY` lost the relation jump and sorted by
another column.

**The fifteen paths where the ORM stayed quiet and returned wrong data.** Reported as one sweep
because they shared a shape: a guard that answered instead of refusing.

**`col == None` emitted `= NULL`** instead of `IS NULL`.

**Row values were not coerced to the declared `python_type`** — psycopg2 handed back a UUID as a
string, a `time` column came back from MySQL as a `timedelta`, and `annotate()` scalars were not
coerced at all.

**Four knobs fell silently, `refresh` degraded a `Decimal`, and `add_all` dropped data.** Same pass:
the debug panel rendered in production and the async pool did not clean up.

**The same DSN named two databases depending on which door you came in by**, and a `file:` DSN was
read as a FILENAME at both ends.

### Fixed — SQLite and MySQL

**SQLite had no transactions.** `rollback()` was a no-op and everything ran in autocommit. Foreign
keys did not exist either, migrations died on the first statement, `WITH RECURSIVE` was broken
entirely, and `.any()`, `.count()` and the four collection aggregates were broken too.

**MySQL ignored the declared date precision** and said nothing. An enum knows its own width and the
ORM threw it away, so MySQL stored TEXT. It has no partial indexes, and the ORM sent it the `WHERE`
all the same. `nulls_last()` emitted syntax it rejects — and that was the guide's own example.

**A model with only an autoincrement PK could not be inserted on ANY engine.**

**`datetime` mapped to a column without a zone**, which drops `tzinfo`.

### Fixed — migrations

**Unique constraints were created and dropped under different names.** The index diff never ran, so
adding an index migrated nothing. `db_comment` was dead metadata that nothing ever emitted. Foreign
keys were diffed by name rather than by definition.

**A `DropForeignKey` vanished silently and tables were dropped in alphabetical order.** A rebuild ate
its table's trigger, and `BIGSERIAL` — which exists only in `CREATE TABLE` — was written into the
`ALTER` too.

**The diff compared `python_type` by IDENTITY** and demanded an empty table rewrite. Only `dict` is
normalised: `list[int]` and `list[str]` land on different SQL types, so unwrapping every origin would
have hidden a real change.

**`snakeorm fresh` worked by luck**, and the pragmas that claimed to save it did nothing.

### Fixed — the scaffolder

**It stopped parsing at a non-English table name** and lost columns without saying so. It mirrored
against `public` and threw away half of what it had already read. It validated the name that comes IN
and wrote the one it DERIVES.

### Changed — breaking

**Each engine gets the DDL grammar it actually speaks.** A capability catalogue answers for the whole
thing, and what an engine cannot do is declared and said out loud rather than stored worse in
silence. A type the engine lacks falls back to TEXT, and the value knows how to come home.

**`snake_column` splits into per-type specifiers**, with two date declarators so the model says which
column it creates, and `SnakeUtc`: an instant that cannot be built wrong.

**A nullable FK demands an optional relationship**, a relation points at ONE model, and a collection
is never optional. `SnakeToOne[Card | Transfer | None]` used to discard `Transfer` in silence.

**Assigning a relation no longer fails silently**, and a missing value shouts instead of vanishing.

**Async reaches the three engines**, with the same protocol and the same composition root. Both
sessions consume the same Plan and the same words, and the drift between them got a test.

**The repository speaks English** — the package, the test suite, and the ORM's own messages to the
user. The prose under `docs/` is bilingual; nothing else is.

### Changed

**The demos declare their shapes and the generator writes them.** Migrating one module surfaced nine
discrepancies between what the dict built and what the model declares. The injection of the model
graph into the globals of eleven foreign modules is gone: the linker reads the `TYPE_CHECKING` block
instead.

**The annotation quoting rule climbs the WHOLE tree, and there are four situations.** Only what does
not exist yet gets quoted, and nothing else. A relative import inside a `TYPE_CHECKING` block is read
now, and six more spellings besides.

**SQL literal formatting moved to the dialect**, which is what made a second engine possible at all.

**The `src/` layout**, zero cycles between packages, and the loose modules at the root grouped into
`core/` and `helpers/`.

### Performance

**The hot path 4.9x**, hydration roughly 2x, and the async streaming that had been crossing the
thread PER ROW.

**The select-in splits by the engine's placeholder ceiling.**

### Fixed — the gates

Listed apart because they break something else: not the user, but the reason to trust a green run.

**`make audit` had been red for pyright** since an unrelated fix, unnoticed. **The gate switch was a
blacklist**, so `off` turned the gates ON. **The MySQL gate sent you to look at Postgres' variables.**
**The type-check of the demos' shared layer measured `Any` and reported Success.** **The integration
tests were skipping silently, and pyright never ran at all.**

## Writing an entry

One line per change somebody using the ORM would notice, under `Added`, `Changed`, `Deprecated`,
`Removed`, `Fixed` or `Security` — only the groups with something in them. Two rules this repository
already applies everywhere else apply here too:

- **Say what changed for the reader, not what was edited.** "`count()` no longer drops `limit()`"
  beats "refactored the query planner".
- **No counts of what the repository IS** — tests, files, supported features. A number nobody
  re-reads goes stale the same day and then lies with authority. A number the entry MEASURED stays,
  because a past measurement does not drift: "the hot path 4.9x" is a fact and will read the same in
  a decade.

A change that alters SQL on one engine and not the others names the engine, because that is the
difference somebody will hit.
