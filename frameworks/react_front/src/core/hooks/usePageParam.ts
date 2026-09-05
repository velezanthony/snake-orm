/**
 * The page number, kept in the URL rather than in state.
 *
 * That is the difference between a control and a page you can send somebody: the back button steps
 * through the pages instead of leaving the section, and a reload lands where it left off.
 *
 * It lives here and not beside `Pager` because a file that exports a component AND a hook breaks
 * Fast Refresh for the whole module — which the linter is what pointed out.
 */

import { useSearchParams } from "react-router";

/** Reads the current page out of the URL. Anything unparseable is page one, not a crash. */
export function usePageParam(): [number, (page: number) => void] {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") ?? 1) || 1);
  const setPage = (next: number) => {
    const copy = new URLSearchParams(params);
    copy.set("page", String(next));
    setParams(copy);
  };
  return [page, setPage];
}
