/**
 * One person's API tokens and open login sessions.
 *
 * IT READS AND IT DOES NOT MINT, which is the line `apps/auth/views.access` draws and the reason
 * this page has no "new token" button: a token is for a client with no cookie jar, and a browser
 * gets a signed session. A ledger you can read is not a mint.
 *
 * The two counts under the heading say **not revoked** and not **still valid** on purpose. The
 * active-tokens query filters on `revoked` and has never looked at `expires_at`, so an expired
 * token is counted — and the expiry is in the table below, where a reader can see for themselves.
 */

import { useParams } from "react-router";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { Badge } from "@atoms/Badge";
import { Card, CardHead } from "@molecules/Card";
import { Code, Muted } from "@atoms/Text";
import { useAccessLedger } from "~/domains/auth/viewmodels";

export function AccessPage() {
  const userId = Number(useParams().userId);

  const ledger = useAccessLedger(userId);

  return (
    <>
      <PageHead
        title={`Access of user ${userId}`}
        lede={
          <>
            This page READS. Minting a token and revoking one stay on <Code>/api/auth/</Code>,
            and the argument was written down before this screen existed: a token is for a client with
            no cookie jar, and a browser gets a signed session. What a ledger you can read is not, is
            a mint.
          </>
        }
      />

      <DataState resource={ledger} loading="Reading the ledger…">
        {({ tokens, notRevoked, sessions }) => (
          <>
            <Muted className="mb-4">
              {notRevoked} of {tokens.length} token{tokens.length === 1 ? "" : "s"} not revoked. It says{" "}
              <strong>not revoked</strong> and not <strong>still valid</strong> on purpose: the query
              behind it filters on <Code>revoked</Code> and has never looked at{" "}
              <Code>expires_at</Code>, so an expired token is counted.
            </Muted>

            <Card className="mb-4">
              <CardHead
                title="API tokens"
                sub="The secret is never here. The DTO next door redacts it too, because a redaction that holds on one surface holds on neither."
              />
              <DataTable
                bare
                label="API tokens"
                caption="Every token this person has been issued, with its state and its dates."
                rows={tokens}
                rowKey={(token) => token.id}
                empty="no tokens issued"
                columns={[
                  { header: "Label", cell: (t) => <span className="font-medium text-ink-900">{t.label || "—"}</span> },
                  { header: "State", cell: (t) => <Badge tone={t.revoked ? "muted" : "ok"}>{t.revoked ? "Revoked" : "Standing"}</Badge> },
                  { header: "Issued", cell: (t) => <span className="muted">{t.created_at}</span> },
                  { header: "Expires", cell: (t) => <span className="muted">{t.expires_at ?? "—"}</span> },
                ]}
              />
            </Card>

            <Card>
              <CardHead
                title="Login sessions"
                sub="The other half of authentication: what a browser gets instead of a token."
              />
              <DataTable
                bare
                label="Login sessions"
                caption="Every login session of this person, with where it came from and when it was last seen."
                rows={sessions}
                rowKey={(session) => session.id}
                empty="no sessions open"
                columns={[
                  { header: "Address", cell: (s) => <span className="font-medium text-ink-900">{s.ip ?? "—"}</span> },
                  { header: "Agent", cell: (s) => <span className="muted">{s.user_agent ?? "—"}</span> },
                  { header: "Opened", cell: (s) => <span className="muted">{s.created_at}</span> },
                  { header: "Last seen", cell: (s) => <span className="muted">{s.last_seen_at ?? "—"}</span> },
                ]}
              />
            </Card>
          </>
        )}
      </DataState>
    </>
  );
}
