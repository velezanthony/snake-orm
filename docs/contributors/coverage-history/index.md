# Coverage history

Every run of `make coverage-snapshot` leaves a JSON snapshot in `assets/data/`, distilled from the
report coverage.py already produces. Those files are the store; nothing else here holds a number.

**[Open the viewer →](coverage/index.html)**

It needs the repository served, because the page fetches its snapshots and a browser refuses that
over `file://` — every such URL is its own origin:

```bash
make coverage-snapshot   # measure, and record it
make coverage-serve      # then open the address it prints
```

## What it shows

Three pages over the same two dates. Pick the same measurement on both sides to look at one moment;
pick different ones and every table gains its comparison.

| page | the question it answers |
|---|---|
| Trend and domains | how the whole thing moved, and which subpackage moved it |
| Files | where the unreached lines actually are |
| Never entered | which functions no test called at all |

That last one is the reason this exists. **A percentage says a line RAN, never that anything was
CHECKED** — and a domain sitting comfortably can still hold whole bodies that no test ever entered,
because an average hides them. Read it next to the star scale in the repository's
`docs/features.md`, where high coverage beside one star is the dangerous combination, not
the reassuring one. That page is not published — it is the project's own index, not user
documentation — which is why this names it instead of linking it.

`partial` is the other column worth watching: branches taken one way only, the `if` that ran while
the `else` never did. It moves when a test gets sharper rather than wider, which is the harder half.

## No numbers on this page

Deliberately. A figure written into a document goes stale the same day and then lies with the
authority of something written down; the viewer reads the snapshots live and cannot. Delete a
snapshot and it leaves the history — there is no second copy anywhere to disagree with it.
