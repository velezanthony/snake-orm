/** Where the snapshots live, relative to the page that loads this. */
export const DATA_DIR = "../assets/data";

/** A directory cannot be listed over HTTP; this file names the snapshots. */
export const MANIFEST = "manifest.json";

/** The series that aggregates every domain. Not a domain name, so it cannot collide with one. */
export const TOTAL = "TOTAL";

/** Shorter functions are properties and `__repr__`s; listing them buries the real ones. */
export const DEAD_FLOOR = 4;

/** The three pages, in sidebar order. `id` is what a page puts in `<body data-page>`. */
export const PAGES = Object.freeze([
  Object.freeze({ id: "trend", href: "./", label: "Trend and domains" }),
  Object.freeze({ id: "files", href: "./files.html", label: "Files" }),
  Object.freeze({ id: "functions", href: "./functions.html", label: "Never entered" }),
]);

/** Ids the pages declare. */
export const EL = Object.freeze({
  chart: "chart",
  series: "series",
  domains: "domains",
  files: "files",
  dead: "dead",
  from: "from",
  to: "to",
  filter: "filter",
  deadFilter: "deadfilter",
  tip: "tip",
  error: "error",
  range: "range",
  rangeHint: "range-hint",
  reset: "range-reset",
  topbar: "topbar",
  sidebar: "sidebar",
  footer: "footer",
});

/** Every class the JavaScript writes. All of them are named in `app.css`; none is a utility. */
export const CSS = Object.freeze({
  code: "code",
  num: "num",
  empty: "empty",
  badge: "badge",
  range: "cov-range",
  stamp: "input cov-stamp",
  hint: "muted cov-hint",
  fieldLabel: "label",
  combo: "cov-combo",
  options: "cov-options",
  option: "cov-option",
  optionEmpty: "cov-option-empty",
  dot: "cov-dot",
  dotSelector: ".cov-dot",
  button: "btn btn-sm",
  buttonOn: "btn-primary",
  buttonOff: "btn-ghost",
  reset: "btn btn-md btn-ghost",
  head: "th-sortable",
  headSorted: "th-sorted",
  sidebarLink: "sidebar-link",
  invalid: "cov-invalid",
  good: "cov-good",
  warn: "cov-warn",
  bad: "cov-bad",
});

/** Query parameters carrying the chosen measurements, so a view is linkable. */
export const QUERY = Object.freeze({ from: "from", to: "to" });

/** Theme tokens, so the chart draws in the same palette as everything else. */
export const INK = Object.freeze({
  grid: "var(--color-ink-200)",
  axis: "var(--color-ink-400)",
  total: "var(--color-brand-600)",
});

/** Percentages at or above which a reading is drawn as good, then as merely warning. */
export const TONE_AT = Object.freeze({ good: 95, warn: 85 });

/** Chart geometry. */
export const CHART = Object.freeze({
  height: 288,
  pad: Object.freeze({ left: 34, right: 12, top: 12, bottom: 26 }),
  gridLines: 4,
  maxTicks: 8,
  headroom: 4,
  dotRadius: 4,
  axisFontSize: 11,
});
