/// <reference path="./types.js" />

import { CHART, CSS, INK, TOTAL } from "./constants.js";
import { label, seriesOf } from "./metrics.js";

const { height, pad, gridLines, maxTicks, headroom, dotRadius, axisFontSize } = CHART;

/** @type {(name: string, domains: string[]) => string} */
const hue = (name, domains) =>
  name === TOTAL ? INK.total : `hsl(${(domains.indexOf(name) * 47) % 360} 55% 45%)`;

/**
 * Draw the trend. The y axis starts below the lowest reading: from zero, a project living between
 * 85 and 95 is a flat stripe and the movement — the only thing a history is for — disappears.
 * @type {(svg: HTMLElement, history: Snapshot[], shown: Set<string>, domains: string[],
 *         onHover: (event: MouseEvent, text: string) => void) => void}
 */
export const drawChart = (svg, history, shown, domains, onHover) => {
  const width = svg.clientWidth || 900;
  const lines = [...shown].map((name) => ({ name, values: seriesOf(history, name) }));
  const all = /** @type {number[]} */ (lines.flatMap((l) => l.values).filter((v) => v !== null));
  const low = Math.max(0, Math.min(...all) - headroom);
  const high = Math.min(100, Math.max(...all) + headroom);
  const span = width - pad.left - pad.right;

  /** @type {(index: number) => number} */
  const x = (index) =>
    pad.left + (history.length < 2 ? span / 2 : (index * span) / (history.length - 1));
  /** @type {(value: number) => number} */
  const y = (value) =>
    pad.top + ((high - value) * (height - pad.top - pad.bottom)) / (high - low || 1);

  const grid = Array.from({ length: gridLines + 1 }, (_, step) => {
    const value = low + (step * (high - low)) / gridLines;
    return (
      `<line x1="${pad.left}" x2="${width - pad.right}" y1="${y(value)}" y2="${y(value)}" stroke="${INK.grid}"/>` +
      `<text x="2" y="${y(value) + 4}" fill="${INK.axis}" font-size="${axisFontSize}">${Math.round(value)}%</text>`
    );
  }).join("");

  const every = Math.ceil(history.length / maxTicks);
  const ticks = history
    .map((snap, index) =>
      history.length < maxTicks || index % every === 0
        ? `<text x="${x(index)}" y="${height - 8}" text-anchor="middle" fill="${INK.axis}" font-size="${axisFontSize}">${label(snap.at)}</text>`
        : "",
    )
    .join("");

  const series = lines
    .map(({ name, values }) => {
      const colour = hue(name, domains);
      const points = values
        .map((value, index) => (value === null ? null : `${x(index)},${y(value)}`))
        .filter(Boolean)
        .join(" ");
      const dots = values
        .map((value, index) =>
          value === null
            ? ""
            : `<circle class="${CSS.dot}" cx="${x(index)}" cy="${y(value)}" r="${dotRadius}" fill="${colour}"
                 data-tip="${name} · ${label(history[index].at)} · ${value}%"/>`,
        )
        .join("");
      return `<polyline fill="none" stroke="${colour}" stroke-width="2" points="${points}"/>${dots}`;
    })
    .join("");

  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = grid + ticks + series;

  for (const dot of svg.querySelectorAll(CSS.dotSelector)) {
    dot.addEventListener("mousemove", (event) =>
      onHover(
        /** @type {MouseEvent} */ (event),
        /** @type {HTMLElement} */ (dot).dataset.tip ?? "",
      ),
    );
  }
};
