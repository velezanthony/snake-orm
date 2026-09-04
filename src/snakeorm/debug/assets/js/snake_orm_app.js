/// <reference path="./language.js" />
/// <reference path="./panel.js" />
/// <reference path="./history.js" />
/**
 * ORCHESTRATOR (`snake_orm_app`) — the controller and owner of the SINGLETON. It takes the host, mounts
 * the panel and WIRES every control to the modules' functions (panel = UI, language = texts,
 * history = the page's later calls), using the VOCABULARIES each module exposes (no loose literals
 * here). It registers the public API on `window.snakeOrmDebug`. No runtime `import`: the modules are
 * concatenated into one inlined `<script type="module">` and share scope (the `///` lines are just
 * for IntelliSense).
 */
const snakeOrmDebug = (() => {
  const { HOST_ID, CLASS, DATA } = SnakeOrmPanel;

  const host = document.getElementById(HOST_ID);
  if (!host || host.dataset[DATA.mounted]) return null; // no panel, or already mounted
  host.dataset[DATA.mounted] = '1';

  const root = SnakeOrmPanel.mount(host);
  const t = SnakeOrmLanguage.t;
  const on = (cls, fn) => root.querySelector(`.${cls}`)?.addEventListener('click', fn);

  // Controls → the modules' functions.
  on(CLASS.close, SnakeOrmPanel.close);
  on(CLASS.backdrop, SnakeOrmPanel.close);
  addEventListener('keydown', (e) => e.key === 'Escape' && SnakeOrmPanel.close());
  on(CLASS.theme, SnakeOrmPanel.theme);
  on(CLASS.toggleAll, () => {
    SnakeOrmPanel.toggleAll();
    SnakeOrmPanel.syncCollapse(t);
  });

  // Queries-per-page selector (25 / 50 / all): on change, it recomputes and repaints.
  const psSelect = root.querySelector(`.${CLASS.ps}`);
  if (psSelect) {
    psSelect.addEventListener('change', () => SnakeOrmPanel.setPageSize(Number(psSelect.value)));
  }
  root.querySelectorAll(`.${CLASS.menuItem}`).forEach((item) =>
    item.addEventListener('click', () => SnakeOrmPanel.showView(item.dataset[DATA.view])),
  );

  // Language selector (<select>): options come from the module, and picking one switches+persists it.
  const langSelect = root.querySelector(`.${CLASS.lang}`);
  if (langSelect) {
    langSelect.innerHTML = Object.entries(SnakeOrmLanguage.NAMES)
      .map(([value, label]) => `<option value="${value}">${label}</option>`)
      .join('');
    langSelect.addEventListener('change', () => {
      SnakeOrmLanguage.set(root, langSelect.value);
      SnakeOrmPanel.syncCollapse(t);
    });
  }

  // Initial language (not persisted): what the user saved, else the one the server sets in the
  // `data-lang` of #snk-root (the panel config), else the module's default.
  SnakeOrmLanguage.apply(
    root,
    SnakeOrmLanguage.stored() || host.dataset.lang || SnakeOrmLanguage.DEFAULT,
  );
  SnakeOrmPanel.syncCollapse(t);

  // The history tab: it watches `fetch`/`XMLHttpRequest` and stacks the calls the page makes after
  // the render. It is mounted LAST and only now, with the panel already up: nothing of the host
  // page gets patched until there is a tab to paint into. The badge is the panel's, so the history
  // asks for it instead of writing it — from here on it counts the queries since the page loaded.
  SnakeOrmHistory.mount(root, {
    translate: t,
    queries: SnakeOrmPanel.badgeCount(),
    onCount: SnakeOrmPanel.badge,
  });

  return {
    open: SnakeOrmPanel.open,
    close: SnakeOrmPanel.close,
    toggle: SnakeOrmPanel.toggle,
    language: SnakeOrmLanguage,
  };
})();

if (snakeOrmDebug) window.snakeOrmDebug = snakeOrmDebug;

export default snakeOrmDebug;
