/**
 * One async read, with the three states a page actually has to render.
 *
 * Every list page in this demo does the same thing: ask the API once, show a spinner while it is in
 * flight, show what came back or what went wrong. Written by hand that is five `useState`s and a
 * race condition — the race being the one where you navigate away, the slow response lands, and it
 * writes into a component that is no longer on screen.
 *
 * `AbortController` is what closes it. Not a `cancelled` flag: an abort actually STOPS the request,
 * so leaving a page mid-load does not leave the browser holding a connection for a body nobody will
 * read.
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface Resource<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  /** Re-runs the read. The operations pages use it after a POST changes something. */
  reload: () => void;
}

export function useResource<T>(
  read: (signal: AbortSignal) => Promise<T>,
  /**
   * What the read depends on. Same contract as a `useEffect` dependency list, and stated the same
   * way, because a hook that tried to be clever about it would be a hook that re-fetches forever.
   */
  deps: readonly unknown[],
): Resource<T> {
  /**
   * ONE piece of state and not three, because the three were never independent: loading with data
   * already set, or an error with `loading` still true, are states this hook cannot be in and had no
   * way of saying so. A single object makes the impossible ones unwritable.
   */
  const [state, setState] = useState<{ data: T | null; error: Error | null; loading: boolean }>({
    data: null,
    error: null,
    loading: true,
  });
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  /**
   * The reset happens DURING RENDER and not inside the effect, which is React's own answer to
   * "adjust state when an input changes" — and the linter is what pointed at the difference.
   *
   * Calling `setState` synchronously in an effect renders once with the old data, once more to say
   * "loading", and again when the answer lands: three renders where two will do, and the middle one
   * shows a spinner over data that was still on screen a frame ago. Setting it while rendering makes
   * React discard this render and redo it before touching the DOM, so nobody ever sees the stale
   * pair.
   */
  const signature = `${JSON.stringify(deps)}#${nonce}`;
  const [asked, setAsked] = useState(signature);
  if (asked !== signature) {
    setAsked(signature);
    setState({ data: null, error: null, loading: true });
  }

  /**
   * `read` is an inline arrow at every call site, so it is a NEW function on every render. Depending
   * on it would re-ask forever; leaving it out of the list would be a lie the linter is right to
   * call out. A ref keeps the latest one reachable without making it a trigger — which is the
   * documented way to say "use the current value, but do not re-run because of it".
   */
  const latest = useRef(read);

  // Written in an EFFECT and not during render: a ref is not a rendering input, and touching
  // `.current` while rendering is how a component ends up reading a value React has not committed.
  // Declared BEFORE the fetch below, because effects run in declaration order — so by the time the
  // fetch runs, on mount and on every change, the ref already holds this render's `read`.
  useEffect(() => {
    latest.current = read;
  });

  useEffect(() => {
    const controller = new AbortController();

    latest.current(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setState({ data: value, error: null, loading: false });
      })
      .catch((cause: unknown) => {
        // An abort is this hook doing its job, not a failure to report.
        if (controller.signal.aborted) return;
        setState({
          data: null,
          error: cause instanceof Error ? cause : new Error(String(cause)),
          loading: false,
        });
      });

    return () => controller.abort();
  }, [signature]);

  return { ...state, reload };
}
