/// <reference path="./types.js" />

import { CSS, EL, QUERY } from "./constants.js";
import { mountCombo } from "./combo.js";

/** @typedef {import("./combo.js").Choice} Choice */
import { label, stampText } from "./metrics.js";

/**
 * The two measurements every page reads, and the one control that picks them.
 *
 * Same on both sides means "show me that moment"; different means "compare the two". One control
 * for both because they are the same question with a narrower or a wider window, and a separate
 * viewer and comparer would be two things to keep in step.
 *
 * Each side is a combobox rather than a `select`: it opens showing every measurement, scrolls
 * inside its own height, and narrows as you type. The choice rides in the query string, so a view is
 * linkable and survives moving between pages.
 *
 * **Left is the older side and right is the same or newer**, and neither field will offer you a date
 * that breaks it — the left one lists nothing after the right, and the right one nothing before the
 * left. Stated as what you can CHOOSE rather than checked after the fact: a rule enforced by
 * refusing a value you were just offered is the same rule written twice, and one copy drifts.
 *
 * The reset appears only once something is off its default, which is the newest measurement on both
 * sides and no filter typed. A button that is always there is one more thing on the page to read
 * every time; one that shows up when there IS something to undo says, by appearing, that you changed
 * something — useful when you arrive from a link and the view is not the one you would have got.
 */

/** @type {(taken: Snapshot[], key: string, fallback: number) => number} */
const asked = (taken, key, fallback) => {
  const wanted = new URLSearchParams(location.search).get(key);
  const found = taken.findIndex((snap) => snap.at === wanted);
  return found === -1 ? fallback : found;
};

/**
 * Put the pair in the query string, or take it out when it is the default.
 *
 * A default view with `?from=…&to=…` on it looks like somebody chose something, and copying that
 * link hands the reader a decision nobody made.
 * @type {(taken: Snapshot[], from: number, to: number, isDefault: boolean) => void}
 */
const remember = (taken, from, to, isDefault) => {
  const url = new URL(location.href);
  if (isDefault) {
    url.searchParams.delete(QUERY.from);
    url.searchParams.delete(QUERY.to);
  } else {
    url.searchParams.set(QUERY.from, taken[from].at);
    url.searchParams.set(QUERY.to, taken[to].at);
  }
  window.history.replaceState({}, "", url);
};

/**
 * Mount the control and report every change. Returns the pair it started on.
 *
 * `filters` are the page's text boxes: the reset clears them too, because "clear what I changed"
 * with a filter still narrowing the table would be a lie in the plainest possible place.
 * @type {(taken: Snapshot[], onChange: (from: number, to: number) => void,
 *         filters?: HTMLInputElement[]) => [number, number]}
 */
export const mountRange = (taken, onChange, filters = []) => {
  const newest = taken.length - 1;
  let from = asked(taken, QUERY.from, newest);
  let to = asked(taken, QUERY.to, newest);

  const host = document.getElementById(EL.range);
  if (!host) return [from, to];

  // Newest first: the one you nearly always want, and a list growing downwards pushes it further
  // away every week.
  const choices = taken
    .map((snap, index) => ({ text: stampText(snap.at), index }))
    .reverse();

  host.innerHTML = `
    <div class="${CSS.range}">
      <div id="${QUERY.from}-field"></div>
      <div id="${QUERY.to}-field"></div>
      <button type="button" id="${EL.reset}" class="${CSS.reset}" hidden>reset</button>
    </div>
    <p class="${CSS.hint}" id="${EL.rangeHint}"></p>`;

  const hint = document.getElementById(EL.rangeHint);

  /** What the two sides measured, when that is not the same thing. @type {(a: Snapshot, b: Snapshot) => string} */
  const mismatch = (a, b) => {
    const one = (a.suites ?? []).join(", ");
    const other = (b.suites ?? []).join(", ");
    if (one === other) return "";
    return ` These measured different suites (${other || "unrecorded"} against ${one || "unrecorded"}), so the difference is the INSTRUMENT and not the tests.`;
  };

  const reset = document.getElementById(EL.reset);

  /** Anything off its default: a side that is not the newest, or a filter with text in it. */
  const dirty = () =>
    from !== newest || to !== newest || filters.some((box) => box.value.trim() !== "");

  const settle = () => {
    if (reset) reset.hidden = !dirty();
    if (hint) {
      hint.textContent =
        from === to
          ? "Both sides name the same measurement, so this is that moment on its own."
          : `Comparing ${label(taken[to].at)} against ${label(taken[from].at)}.` +
            mismatch(taken[from], taken[to]);
    }
    remember(taken, from, to, from === newest && to === newest);
    onChange(from, to);
  };

  /**
   * @type {(key: string, caption: string, chosen: number, legal: () => Choice[],
   *         apply: (index: number) => void) => void}
   */
  const side = (key, caption, chosen, legal, apply) => {
    const box = document.getElementById(`${key}-field`);
    if (!box) return;
    const selected = choices.find((choice) => choice.index === chosen);
    if (!selected) return;
    mountCombo(box, key, caption, legal, selected, (index) => {
      apply(index);
      settle();
    });
  };

  side(
    QUERY.from,
    "from",
    from,
    () => choices.filter((choice) => choice.index <= to),
    (index) => {
      from = index;
    },
  );
  side(
    QUERY.to,
    "to",
    to,
    () => choices.filter((choice) => choice.index >= from),
    (index) => {
      to = index;
    },
  );

  // The filters do not go through `settle` —they redraw their own table— so the button would not
  // notice them appearing. It only toggles here; nothing else needs redrawing.
  for (const box of filters) {
    box.addEventListener("input", () => {
      if (reset) reset.hidden = !dirty();
    });
  }

  reset?.addEventListener("click", () => {
    from = newest;
    to = newest;
    for (const box of filters) box.value = "";
    for (const box of host.querySelectorAll("input[role='combobox']")) {
      const field = /** @type {HTMLInputElement} */ (box);
      field.value = stampText(taken[newest].at);
      field.classList.remove(CSS.invalid);
      field.setAttribute("aria-invalid", "false");
    }
    settle();
  });

  settle();
  return [from, to];
};
