/// <reference path="./types.js" />

import { CSS } from "./constants.js";

/**
 * Render a table whose headings sort it. Re-rendered whole on every sort: with a few hundred rows
 * that is instant, and it keeps one path from data to DOM.
 * @type {<T extends (string | number | null)[]>(
 *   table: HTMLElement, rows: T[], columns: Column<T>[], initial: number
 * ) => void}
 */
export const sortable = (table, rows, columns, initial) => {
  let by = initial;
  let descending = true;

  const draw = () => {
    const sorted = [...rows].sort((left, right) => {
      const [a, b] = [left[by], right[by]];
      const order =
        typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
      return descending ? -order : order;
    });

    const head = columns
      .map(
        (column, index) =>
          `<th data-index="${index}" class="${CSS.head} ${index === by ? CSS.headSorted : ""}">${column.head}</th>`,
      )
      .join("");
    const body = sorted.length
      ? sorted
          .map((row) => `<tr>${columns.map((c) => `<td>${c.cell(row)}</td>`).join("")}</tr>`)
          .join("")
      : `<tr><td colspan="${columns.length}" class="${CSS.empty}">nothing to show</td></tr>`;

    table.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
    for (const th of table.querySelectorAll("th")) {
      th.addEventListener("click", () => {
        const index = Number(th.dataset.index);
        if (index === by) descending = !descending;
        else [by, descending] = [index, true];
        draw();
      });
    }
  };

  draw();
};

/** @type {(text: string) => string} */
export const code = (text) => `<code class="${CSS.code}">${text}</code>`;

/** @type {(value: string | number | null, extra?: string) => string} */
export const num = (value, extra = "") =>
  `<span class="${CSS.num} ${extra}">${value}</span>`;
