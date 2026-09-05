/// <reference path="./types.js" />

import { CSS, TONE_AT, TOTAL } from "./constants.js";

/**
 * Lines and branches together, as `coverage report` computes its single column.
 * @type {(rows: Row[]) => number}
 */
export const pct = (rows) => {
  const hit = rows.reduce((total, row) => total + row[1] + row[3], 0);
  const all = rows.reduce((total, row) => total + row[0] + row[2], 0);
  return all ? Math.round((100 * hit) / all) : 100;
};

/** Statements and branches never reached. @type {(row: Row) => number} */
export const miss = (row) => row[0] - row[1] + (row[2] - row[3]);

/** `2026-08-29T173638` → `08-29 17:36`. @type {(stamp: string) => string} */
export const label = (stamp) =>
  `${stamp.slice(5, 10)} ${stamp.slice(11, 13)}:${stamp.slice(13, 15)}`;

/**
 * `2026-08-29T180442` → `2026-08-29 18:04:42`, which is what you type into the picker.
 *
 * The whole stamp, not the short label: it is unique —two runs in one minute would otherwise name
 * the same thing— and every part of it is worth typing to narrow the list, day or hour.
 * @type {(stamp: string) => string}
 */
export const stampText = (stamp) => {
  const [day, clock] = stamp.split("T");
  return `${day} ${clock.slice(0, 2)}:${clock.slice(2, 4)}:${clock.slice(4, 6)}`;
};

/** @type {(percent: number) => string} */
export const tone = (percent) =>
  percent >= TONE_AT.good ? CSS.good : percent >= TONE_AT.warn ? CSS.warn : CSS.bad;

/**
 * One domain across every snapshot; `null` where it did not exist yet.
 * @type {(history: Snapshot[], name: string) => (number | null)[]}
 */
export const seriesOf = (history, name) =>
  history.map((snap) =>
    name === TOTAL
      ? pct(Object.values(snap.domains))
      : snap.domains[name]
        ? pct([snap.domains[name]])
        : null,
  );
