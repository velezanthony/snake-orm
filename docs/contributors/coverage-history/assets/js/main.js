/// <reference path="./types.js" />

import { CSS, DEAD_FLOOR, EL, PAGES, TOTAL } from "./constants.js";
import { drawChart } from "./chart.js";
import { label, miss, pct, tone } from "./metrics.js";
import { load } from "./load.js";
import { mountRange } from "./range.js";
import { mountShell, syncLinks } from "./shell.js";
import { code, num, sortable } from "./table.js";

/** @type {(id: string) => HTMLElement | null} */
const find = (id) => document.getElementById(id);

/** @type {(id: string) => HTMLInputElement} */
const input = (id) => /** @type {HTMLInputElement} */ (find(id));

/** @type {(event: MouseEvent, text: string) => void} */
const showTip = (event, text) => {
  const tip = find(EL.tip);
  if (!tip) return;
  tip.textContent = text;
  tip.style.left = `${event.clientX + 12}px`;
  tip.style.top = `${event.clientY - 28}px`;
  tip.style.opacity = "1";
};

/** @type {(message?: string) => void} */
const fail = (message) => {
  const box = find(EL.error);
  if (!box) return;
  if (message) box.textContent = message;
  box.hidden = false;
};

/** `·` where there is nothing to compare: `+0` would read as "measured, unchanged".
 * @type {(now: number | null, was: number | null, comparing: boolean) => string} */
const move = (now, was, comparing) => {
  if (!comparing || now === null || was === null) return "·";
  const change = now - was;
  return num(`${change >= 0 ? "+" : ""}${change}`);
};

/** @type {(taken: Snapshot[], domains: string[]) => void} */
const mountTrend = (taken, domains) => {
  const svg = find(EL.chart);
  const box = find(EL.series);
  if (!svg || !box) return;

  const shown = new Set([TOTAL]);
  const chart = () => drawChart(svg, taken, shown, domains, showTip);

  const buttons = () => {
    box.innerHTML = [TOTAL, ...domains]
      .map(
        (name) =>
          `<button data-name="${name}" class="${CSS.button} ${
            shown.has(name) ? CSS.buttonOn : CSS.buttonOff
          }">${name}</button>`,
      )
      .join("");
    for (const button of box.querySelectorAll("button")) {
      button.addEventListener("click", () => {
        const name = button.dataset.name ?? "";
        if (shown.has(name)) shown.delete(name);
        else shown.add(name);
        if (!shown.size) shown.add(TOTAL);
        buttons();
        chart();
      });
    }
  };

  addEventListener("resize", chart);
  buttons();
  chart();
};

/** @type {(domains: string[], from: Snapshot, to: Snapshot) => void} */
const drawDomains = (domains, from, to) => {
  const table = find(EL.domains);
  if (!table) return;
  const comparing = from !== to;

  const rows = domains.map((name) => {
    const now = to.domains[name];
    const was = from.domains[name];
    return [
      name,
      now ? pct([now]) : null,
      was ? pct([was]) : null,
      now ? now[4] : 0,
      now ? miss(now) : 0,
    ];
  });

  sortable(
    table,
    rows,
    [
      { head: "domain", cell: (row) => code(String(row[0])) },
      {
        head: label(to.at),
        cell: (row) => (row[1] === null ? "—" : num(`${row[1]}%`, tone(Number(row[1])))),
      },
      { head: "move", cell: (row) => move(row[1], row[2], comparing) },
      { head: "partial", cell: (row) => num(row[3]) },
      { head: "unreached", cell: (row) => num(row[4]) },
    ],
    4,
  );
};

/** @type {(from: Snapshot, to: Snapshot) => void} */
const drawFiles = (from, to) => {
  const table = find(EL.files);
  if (!table) return;
  const comparing = from !== to;
  const needle = input(EL.filter).value.toLowerCase();

  const rows = Object.entries(to.files)
    .filter(([path]) => path.toLowerCase().includes(needle))
    .map(([path, row]) => {
      const was = from.files[path];
      return [path, pct([row]), was ? pct([was]) : null, miss(row), row[0], row[4]];
    });

  sortable(
    table,
    rows,
    [
      { head: "file", cell: (row) => code(String(row[0])) },
      { head: "covered", cell: (row) => num(`${row[1]}%`, tone(Number(row[1]))) },
      { head: "move", cell: (row) => move(row[1], row[2], comparing) },
      { head: "unreached", cell: (row) => num(row[3]) },
      { head: "statements", cell: (row) => num(row[4]) },
      { head: "partial", cell: (row) => num(row[5]) },
    ],
    3,
  );
};

/** @type {(snap: Snapshot) => Set<string>} */
const deadIn = (snap) =>
  new Set(
    Object.entries(snap.functions ?? {})
      .filter(([, row]) => row[1] === 0 && row[0] >= DEAD_FLOOR)
      .map(([name]) => name),
  );

/**
 * Dead functions of the shown measurement. When comparing, `since` marks the ones that were
 * entered before and are not now — a body a test used to reach and no longer does.
 * @type {(from: Snapshot, to: Snapshot) => void}
 */
const drawDead = (from, to) => {
  const table = find(EL.dead);
  if (!table) return;
  const comparing = from !== to;
  const before = comparing ? deadIn(from) : null;
  const needle = input(EL.deadFilter).value.toLowerCase();

  const rows = [...deadIn(to)]
    .filter((name) => name.toLowerCase().includes(needle))
    .map((name) => {
      const row = to.functions[name];
      return [name, row[0], row[2], before && !before.has(name) ? "new" : "·"];
    });

  sortable(
    table,
    rows,
    [
      { head: "function", cell: (row) => code(String(row[0])) },
      { head: "statements", cell: (row) => num(row[1]) },
      { head: "branches", cell: (row) => num(row[2]) },
      { head: "since", cell: (row) => (row[3] === "new" ? `<span class="badge">new</span>` : "·") },
    ],
    1,
  );
};

const start = async () => {
  mountShell(document.body.dataset.page ?? PAGES[0].id);

  /** @type {Snapshot[]} */
  let taken = [];
  try {
    taken = await load();
  } catch (error) {
    console.error(error);
    return fail();
  }
  if (!taken.length) return fail("No snapshots yet. Run `make coverage-snapshot`.");

  const domains = Object.keys(taken[taken.length - 1].domains).sort();

  document.addEventListener("mouseout", (event) => {
    const tip = find(EL.tip);
    if (tip && /** @type {HTMLElement} */ (event.target).closest?.(CSS.dotSelector)) {
      tip.style.opacity = "0";
    }
  });

  mountTrend(taken, domains);

  // The pair lives here because the filters redraw too, and they must use the CURRENT one — reading
  // the value the range started on would filter yesterday's measurement without saying so.
  let shownRange = [taken.length - 1, taken.length - 1];

  /** @type {(fromIndex: number, toIndex: number) => void} */
  const redraw = (fromIndex, toIndex) => {
    shownRange = [fromIndex, toIndex];
    syncLinks();
    const [from, to] = [taken[fromIndex], taken[toIndex]];
    drawDomains(domains, from, to);
    drawFiles(from, to);
    drawDead(from, to);
  };

  for (const id of [EL.filter, EL.deadFilter]) {
    find(id)?.addEventListener("input", () => redraw(shownRange[0], shownRange[1]));
  }
  const filters = /** @type {HTMLInputElement[]} */ (
    [EL.filter, EL.deadFilter].map(find).filter(Boolean)
  );
  const [fromIndex, toIndex] = mountRange(taken, redraw, filters);
  if (!find(EL.range)) redraw(fromIndex, toIndex);
};

start();
