/// <reference path="./types.js" />

import { CSS, EL, PAGES } from "./constants.js";

/**
 * The chrome every page shares. Only the CONTENT is built here: the structural elements carry
 * `.topbar`, `.sidebar` and `.footer` in the HTML, because `.layout` lays out its direct children
 * and a wrapper injected around them would break the grid.
 */

/** What you are looking at travels with you between pages. @type {() => string} */
const carry = () => location.search;

/** @type {(current: string) => string} */
const sidebar = (current) => `
  <div class="sidebar-group">
    <p class="sidebar-title">Coverage</p>
    ${PAGES.map(
      (page) =>
        `<a class="${CSS.sidebarLink}" href="${page.href}${carry()}"${
          page.id === current ? ' aria-current="page"' : ""
        }>${page.label}</a>`,
    ).join("")}
    <p class="sidebar-blurb">
      Recorded by <code class="code">make coverage-snapshot</code>. A percentage says a line ran,
      never that anything was checked.
    </p>
  </div>`;

const topbar = `
  <div class="topbar-inner">
    <a class="brand" href="./">
      <span class="brand-mark" aria-hidden="true">S</span>
      <span class="brand-name">SnakeORM · coverage</span>
    </a>
  </div>`;

const footer = `
  <div class="footer-inner">
    <p>Read beside the roadmap's stars: coverage says a line ran, the stars say what was checked.</p>
    <p><code class="code">make coverage-snapshot</code> · <code class="code">make coverage-serve</code></p>
  </div>`;

/**
 * Point the sidebar at what is on screen NOW.
 *
 * The hrefs are built once at mount, so without this a comparison chosen afterwards is dropped the
 * moment you move to another page — you would arrive looking at something else and nothing would
 * say so.
 */
export const syncLinks = () => {
  for (const link of document.querySelectorAll(`.${CSS.sidebarLink}`)) {
    const anchor = /** @type {HTMLAnchorElement} */ (link);
    anchor.search = carry();
  }
};

/** @type {(current: string) => void} */
export const mountShell = (current) => {
  /** @type {(id: string, html: string) => void} */
  const fill = (id, html) => {
    const host = document.getElementById(id);
    if (host) host.innerHTML = html;
  };
  fill(EL.topbar, topbar);
  fill(EL.sidebar, sidebar(current));
  fill(EL.footer, footer);
};
