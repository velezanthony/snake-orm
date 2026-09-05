"""Record the coverage history and rebuild what reads it.

    history.py snapshot <coverage.json> <stamp> <suites>
    history.py render

`snapshot` distils the report coverage.py already produces, so it can never disagree with
`make coverage`. `render` rewrites the manifest the page fetches.

`index.md` is NOT generated: it explains what this is and links to the viewer, and carries no
figure at all. One written down goes stale the same day and then lies with the authority of a
document, while the page reads the snapshots live and cannot.

The JSON snapshots are the store; every view is derived and can be deleted and rebuilt. Line NUMBERS
are dropped — 1.5 MB per run describing a tree the next commit changes.

Each one records WHICH SUITES produced it, and that field earns its place. When `make coverage` began
running the demos as well, `asyncsession.py` went from 65% to 87% between two snapshots and nobody
had written a test: the instrument had changed, and the history would have shown it as a win. Two
measurements of different things cannot be compared, and now the data says so.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "assets" / "data"

# statements, covered, branches, covered branches, partial.
_Row = list[int]
_Table = dict[str, _Row]


def _row(summary: dict[str, int]) -> _Row:
    return [
        summary["num_statements"],
        summary["covered_lines"],
        summary["num_branches"],
        summary["covered_branches"],
        summary["num_partial_branches"],
    ]


def _domain(path: str) -> str:
    """The subpackage a file belongs to; top-level modules answer for themselves."""
    head, _, tail = path.partition("/")
    return head if tail else "(root)"


def snapshot(source: Path, stamp: str, suites: str) -> None:
    """Distil coverage.py's JSON report into a snapshot named by the timestamp."""
    raw = json.loads(source.read_text(encoding="utf-8"))
    files: _Table = {}
    domains: _Table = {}
    functions: _Table = {}

    for path, entry in raw["files"].items():
        name = path.removeprefix("src/snakeorm/")
        row = _row(entry["summary"])
        files[name] = row
        current = domains.get(_domain(name))
        domains[_domain(name)] = (
            row.copy() if current is None else [a + b for a, b in zip(current, row)]
        )
        for function, body in entry.get("functions", {}).items():
            functions[f"{name}::{function}"] = _row(body["summary"])

    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / f"{stamp}.json").write_text(
        json.dumps(
            {
                "at": stamp,
                "coverage": raw["meta"]["version"],
                "suites": sorted(suites.split(",")),
                "domains": domains,
                "files": files,
                "functions": functions,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def _load() -> list[dict[str, object]]:
    """Every snapshot on disk. The filename is the timestamp, so sorting is chronology."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(_DATA.glob("20*.json"))
    ]


def _manifest(history: list[dict[str, object]]) -> None:
    """A directory cannot be listed over HTTP, so the page reads this instead."""
    _DATA.mkdir(parents=True, exist_ok=True)
    (_DATA / "manifest.json").write_text(
        json.dumps({"snapshots": [f"{snap['at']}.json" for snap in history]}, indent=1)
        + "\n",
        encoding="utf-8",
    )


def render() -> None:
    """Rewrite the manifest from whatever snapshots are on disk."""
    _manifest(_load())


def main(argv: list[str]) -> int:
    if argv[1:2] == ["snapshot"] and len(argv) == 5:
        snapshot(Path(argv[2]), argv[3], argv[4])
        return 0
    if argv[1:2] == ["render"]:
        render()
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
