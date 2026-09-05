/**
 * The linter, and it is a HARD GATE — the same standing `ruff` has on the Python side.
 *
 * WHY IT EXISTS, MEASURED. This client went eight commits without one, and the audit that closed the
 * refactor found what that costs: two `eslint-disable` comments pointing at rules of a tool that was
 * not installed, and the single `any` in the codebase sitting underneath one of them. Nobody noticed,
 * because nothing was looking. `tsc` cannot see either of those: a comment is a comment, and `any` is
 * a valid type.
 *
 * IT IS TYPE-AWARE on purpose (`recommendedTypeChecked`). The cheap setup lints syntax and would have
 * caught neither of the two. The rules that earn the extra cost are the ones about `any` leaking
 * through a boundary and about a promise nobody awaited — and this app is almost entirely promises.
 *
 * The config file itself is `.js` rather than `.ts`: ESLint reads it with Node directly, and a
 * TypeScript config would need a loader in a project that otherwise has none.
 */

import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // Build output and dependencies. `dist/` is generated and `node_modules/` is not ours.
  { ignores: ["dist", "node_modules", "eslint.config.js", "vite.config.ts"] },

  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,

  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,

      // A component file that also exports something else breaks Fast Refresh for the whole module.
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      // CERO `any`, which is the rule this repository states for its Python and had never stated for
      // its TypeScript. An error and not a warning: a warning is a thing you scroll past.
      "@typescript-eslint/no-explicit-any": "error",

      // A disable comment for a rule that never fired is the shape of the two this audit found.
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },

  {
    // The type-level tests exist to make illegal code, so the rules that object to illegal code have
    // nothing to say about them. `tsc` is their runner and their assertions are `@ts-expect-error`.
    files: ["**/*.types.test.tsx"],
    rules: {
      "@typescript-eslint/no-unused-vars": "off",
      "@typescript-eslint/no-unused-expressions": "off",
      // A line under `@ts-expect-error` has the type `error`, and every rule that reads types has an
      // opinion about it. They are all the same opinion: "this does not compile", which is the
      // assertion.
      "@typescript-eslint/no-unsafe-return": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
    },
  },
);
