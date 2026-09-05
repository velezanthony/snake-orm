/**
 * The route error boundary, and the mirror of `templates/layout/error.html`.
 *
 * It is attached at the layout route so a thrown render still comes out inside the shell: an error
 * that loses the topbar and the sidebar strands the reader on a page with nowhere to go.
 */

import { isRouteErrorResponse, useRouteError } from "react-router";

import { ButtonLink } from "@atoms/Button";

import { messageFor } from "~/core/hooks/useAction";

export function ErrorPage() {
  const error = useRouteError();

  const title = isRouteErrorResponse(error) ? `${error.status} ${error.statusText}` : "Something broke";
  // `error.data` is whatever a loader threw, so `unknown` is the honest type for it and
  // `String()` the honest way to show it. Reading it as `any` was the linter's finding.
  const detail: unknown = isRouteErrorResponse(error) ? error.data : messageFor(error);

  return (
    <div className="page-head">
      <h1 className="h1">{title}</h1>
      <p className="lede">{String(detail)}</p>
      <p className="pt-2">
        <ButtonLink to="/">Back to the posts</ButtonLink>
      </p>
    </div>
  );
}

/** A URL this client does not serve. Separate from the boundary: nothing went wrong, it just is not here. */
export function NotFoundPage() {
  return (
    <div className="page-head">
      <h1 className="h1">404</h1>
      <p className="lede">This client has no page at that address.</p>
      <p className="pt-2">
        <ButtonLink to="/">Back to the posts</ButtonLink>
      </p>
    </div>
  );
}
