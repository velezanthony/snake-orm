import type { ReactNode } from "react";

import { Alert } from "@molecules/Alert";
import { PageSpinner } from "@atoms/Spinner";
import { messageFor } from "~/core/hooks/useAction";
import type { Resource } from "~/core/hooks/useResource";

/**
 * Renders the three outcomes of a read, so no page has to write the same ternary again.
 *
 * The children only run once there IS data, which is the point: the callback takes a `T` and not a
 * `T | null`, so a page cannot accidentally render a table against nothing.
 */
export function DataState<T>({
  resource,
  loading,
  children,
}: {
  resource: Resource<T>;
  loading?: string;
  children: (data: T) => ReactNode;
}) {
  if (resource.error !== null) return <Alert kind="error">{messageFor(resource.error)}</Alert>;
  if (resource.data === null) return <PageSpinner label={loading} />;
  return <>{children(resource.data)}</>;
}
