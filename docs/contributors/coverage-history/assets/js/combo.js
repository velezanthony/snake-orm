/// <reference path="./types.js" />

import { CSS } from "./constants.js";

/**
 * A date field that lists every measurement and narrows as you type.
 *
 * A `<datalist>` was the first try. It costs no JavaScript, but the popup belongs to the browser:
 * you cannot cap its height, cannot style it, and cannot promise it opens on a click — and the
 * matching rule differs between engines. Since the whole point is "show them all, scrolling, without
 * the list growing a row a week", the height had to be ours.
 */

/** @typedef {{ text: string, index: number }} Choice */

const KEY = Object.freeze({
  down: "ArrowDown",
  up: "ArrowUp",
  enter: "Enter",
  escape: "Escape",
  tab: "Tab",
});

/** @type {(choices: Choice[], needle: string) => Choice[]} */
const matching = (choices, needle) =>
  needle ? choices.filter((choice) => choice.text.includes(needle)) : choices;

/**
 * Build one field. `onPick` fires only for a real measurement, never mid-typing.
 *
 * `legal` is asked EVERY time the list opens, not read once: the two sides constrain each other, so
 * what this field may offer changes when the other one moves. Offering a choice and then refusing it
 * would be the same rule stated twice, and one of the two would drift.
 * @type {(host: HTMLElement, id: string, caption: string, legal: () => Choice[], selected: Choice,
 *         onPick: (index: number) => void) => void}
 */
export const mountCombo = (host, id, caption, legal, selected, onPick) => {
  const listId = `${id}-options`;
  host.innerHTML = `
    <label class="${CSS.fieldLabel}" for="${id}">${caption}</label>
    <div class="${CSS.combo}">
      <input id="${id}" class="${CSS.stamp}" value="${selected.text}" role="combobox"
             aria-expanded="false" aria-controls="${listId}" aria-autocomplete="list"
             autocomplete="off" spellcheck="false" placeholder="type to narrow…">
      <ul id="${listId}" class="${CSS.options}" role="listbox" hidden></ul>
    </div>`;

  const field = /** @type {HTMLInputElement} */ (host.querySelector("input"));
  const list = /** @type {HTMLElement} */ (host.querySelector("ul"));
  /** @type {Choice[]} */
  let visible = legal();
  let active = -1;

  const close = () => {
    list.hidden = true;
    field.setAttribute("aria-expanded", "false");
    active = -1;
  };

  const paint = () => {
    list.innerHTML = visible.length
      ? visible
          .map(
            (choice, row) =>
              `<li class="${CSS.option}" role="option" data-index="${choice.index}"
                   aria-selected="${row === active}">${choice.text}</li>`,
          )
          .join("")
      : `<li class="${CSS.optionEmpty}">no measurement matches</li>`;
    if (active >= 0) list.children[active]?.scrollIntoView({ block: "nearest" });
  };

  const open = () => {
    list.hidden = false;
    field.setAttribute("aria-expanded", "true");
    paint();
  };

  /** Take a row: fill the field, close, and report. @type {(row: number) => void} */
  const take = (row) => {
    const choice = visible[row];
    if (!choice) return;
    field.value = choice.text;
    field.classList.remove(CSS.invalid);
    field.setAttribute("aria-invalid", "false");
    close();
    onPick(choice.index);
  };

  /** @type {(step: number) => void} */
  const step = (offset) => {
    if (list.hidden) return open();
    active = (active + offset + visible.length) % visible.length;
    paint();
  };

  field.addEventListener("focus", () => {
    visible = legal();
    open();
  });

  field.addEventListener("input", () => {
    const typed = field.value.trim();
    const allowed = legal();
    visible = matching(allowed, typed);
    active = -1;
    open();

    // Only an exact measurement moves the view. Redrawing on whatever a half-typed date matches
    // would flicker through the ones on the way, and clearing the field would throw away the
    // comparison being built — so a partial value is marked and otherwise left alone.
    const exact = allowed.find((choice) => choice.text === typed);
    field.classList.toggle(CSS.invalid, !exact);
    field.setAttribute("aria-invalid", String(!exact));
    if (exact) onPick(exact.index);
  });

  field.addEventListener("keydown", (event) => {
    if (event.key === KEY.down) {
      event.preventDefault();
      step(1);
    } else if (event.key === KEY.up) {
      event.preventDefault();
      step(-1);
    } else if (event.key === KEY.enter && active >= 0) {
      event.preventDefault();
      take(active);
    } else if (event.key === KEY.escape || event.key === KEY.tab) {
      close();
    }
  });

  // `mousedown` and not `click`: the field blurs first, and a handler that waited for the click
  // would be racing the close.
  list.addEventListener("mousedown", (event) => {
    const option = /** @type {HTMLElement} */ (event.target).closest(`.${CSS.option}`);
    if (!option) return;
    event.preventDefault();
    take(visible.findIndex((choice) => choice.index === Number(option.getAttribute("data-index"))));
  });

  document.addEventListener("click", (event) => {
    if (!host.contains(/** @type {Node} */ (event.target))) close();
  });
};
