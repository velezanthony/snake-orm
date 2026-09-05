/**
 * The control this demo exists to have: which of the three APIs the app is talking to.
 *
 * It is a `<select>` in the topbar next to the others, styled `select-inline` like them, because
 * changing backend is the same KIND of act as opening the JSON or signing out — a developer's
 * switch, not a feature of the domain.
 */

import { InlineSelect } from "@atoms/Field";
import { BACKENDS, BACKEND_IDS, currentBackend, switchBackend, type BackendId } from "~/config/backends";

export function BackendSwitcher() {
  const backend = currentBackend();

  return (
    <InlineSelect
      aria-label={`API: ${backend.label}`}
      value={backend.id}
      onChange={(event) => switchBackend(event.target.value as BackendId)}
    >
      {BACKEND_IDS.map((id) => (
        <option key={id} value={id}>
          API · {BACKENDS[id].label}
        </option>
      ))}
    </InlineSelect>
  );
}
