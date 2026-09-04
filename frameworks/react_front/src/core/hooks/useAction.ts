/**
 * One WRITE, with the state a form actually has to render: in flight, and what went wrong.
 *
 * The counterpart of `useResource`, and deliberately not the same hook: a read starts itself and a
 * write is started by a person. Folding both into one would mean a flag deciding which of the two
 * it is this time.
 */

import { useCallback, useState } from "react";

import { ApiError } from "~/core/http/client";

/** The `detail` codes the three APIs agree on, turned into something a person can read. */
const MESSAGES: Record<string, string> = {
  missing_fields: "Fill in every field.",
  taken: "That username is already taken.",
  bad_credentials: "Wrong user or password.",
  not_found: "That does not exist.",
  forbidden: "That is not yours to change.",
  "authentication required": "Sign in first.",
};

export function messageFor(error: unknown): string {
  if (error instanceof ApiError) return MESSAGES[error.detail] ?? error.detail;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

export interface Action<Args extends unknown[], Result> {
  run: (...args: Args) => Promise<Result | undefined>;
  pending: boolean;
  error: string | null;
  reset: () => void;
}

export function useAction<Args extends unknown[], Result>(
  perform: (...args: Args) => Promise<Result>,
): Action<Args, Result> {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (...args: Args) => {
      setPending(true);
      setError(null);
      try {
        return await perform(...args);
      } catch (cause: unknown) {
        // Swallowed HERE and nowhere else: the caller gets `undefined` back and the message lands
        // in `error`, so a form can render the failure instead of the page unmounting into a
        // boundary. A write that fails is an ordinary outcome of a form.
        setError(messageFor(cause));
        return undefined;
      } finally {
        setPending(false);
      }
    },
    [perform],
  );

  const reset = useCallback(() => setError(null), []);

  return { run, pending, error, reset };
}
