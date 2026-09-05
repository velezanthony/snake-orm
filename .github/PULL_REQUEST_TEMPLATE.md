## What

<!-- One or two lines. What changes for somebody using the ORM? -->

## Why

<!-- The problem, not the patch. If it is a bug: what did it do, and what did you expect?
     If you can, paste what you measured — the wrong SQL, the message, the two engines disagreeing. -->

## How

<!-- The decision, if there was one. What else did you consider, and why did this win?
     If the answer is "there was only one way", say that and move on. -->

---

## Before asking for a review

- [ ] **`make audit`** passes. It is what CI runs, and it is not the same as `uv run pytest`.
- [ ] **The engines were up.** Without them a large part of the suite SKIPS and comes out green, so
      a change verified with the database off is a change that was not verified:
      `docker compose up -d db mysql` and then
      `SNAKEORM_REQUIRE_POSTGRES=true SNAKEORM_REQUIRE_MYSQL=true uv run pytest -q -rs`.
      Every remaining skip should say `cannot`.
- [ ] **The test was seen RED first**, and the message says which. A net nobody has watched fail is
      not a net — half the defects this repository has fixed were tests that could not fail.
- [ ] **New code is in English** — identifiers, comments, docstrings and any string the ORM emits.
      The prose in `docs/` is the only thing that speaks two.

### If you touched documentation

- [ ] The `.es.md` twin says the SAME thing. Not a literal translation — the same claims.
- [ ] Code blocks are **identical** in both, byte for byte, comments included.
- [ ] Any error message you quote was **provoked and copied**, not written from memory.
- [ ] **No counts.** Not tests, not files, not "exactly two extras". A number nobody re-reads goes
      stale the same day and then lies with authority. Say what there IS and where; the count comes
      from running the command.
- [ ] A new page is registered in `nav` **and** in `nav_translations` (two places, same file).

### If you touched a dialect or a driver

- [ ] The `Cap` catalogue answers for the whole thing — `Full()`, `Degraded(reason)` or
      `Nope(reason)`. Forgetting one blows up at import, which is the point.
- [ ] What an engine cannot do is **declared and said out loud**. Storing worse and keeping quiet is
      the one thing this ORM never does.
