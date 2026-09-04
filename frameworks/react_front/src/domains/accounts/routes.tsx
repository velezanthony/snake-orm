/**
 * The accounts routes. Two, and no update or delete of a role: the same argument taxonomy makes
 * about a tag, and the API offers neither operation either.
 */

import { defineDomain } from "~/core/routing/domain";
import { AccountsDetailPage } from "~/domains/accounts/pages/AccountsDetailPage";
import { AccountsListPage } from "~/domains/accounts/pages/AccountsListPage";

export const accountsRoutes = defineDomain("/accounts", {
  list: { segment: "", element: <AccountsListPage />, nav: "Roles & people" },
  detail: { segment: ":userId", element: <AccountsDetailPage /> },
});
