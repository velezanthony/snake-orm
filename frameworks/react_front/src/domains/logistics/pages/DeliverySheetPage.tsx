/**
 * The page this domain exists for.
 *
 * The ranking below is a SQRT over a sum of POWERs computed by the ENGINE, so it can be the ORDER BY
 * key and only the three depots that win ever travel. The picking slip beside it divides the same two
 * numbers TWICE — rounded UP for the labels, DOWN for the boxes that leave sealed — and the gap
 * between them is the loose picking somebody does by hand.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";
import { Badge } from "@atoms/Badge";
import { ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { DescriptionList } from "@molecules/DescriptionList";
import { PageHead } from "@molecules/PageHead";
import { DataState } from "@organisms/DataState";
import { DataTable } from "@organisms/DataTable";
import { useDeliverySheet } from "~/domains/logistics/viewmodels";

export function DeliverySheetPage() {
  const deliveryId = Number(useParams().deliveryId);
  const sheet = useDeliverySheet(deliveryId);

  return (
    <DataState resource={sheet} loading="Reading the sheet…">
      {(data) => (
        <>
          <PageHead
            title={`Delivery ${data.reference}`}
            lede="The ranking below is a SQRT over a sum of POWERs computed by the ENGINE, so it can be the ORDER BY key and only the three depots that win ever travel. The picking slip beside it divides the same two numbers twice — rounded UP for the labels, DOWN for the boxes that leave sealed — and the gap between them is the loose picking somebody does by hand."
            actions={
              <ButtonLink size="sm" to={href("logistics.dispatch")}>
                ← Dispatch board
              </ButtonLink>
            }
          />

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHead
                title="Nearest depots"
                sub="A distance the engine computed, used as the ORDER BY key — so only the winners travel."
                aside={data.is_routed_to_the_nearest ? <Badge tone="ok">On the nearest</Badge> : <Badge>Not the nearest</Badge>}
              />
              <DataTable
                bare
                label="Nearest depots"
                caption="The depots ranked by distance, with the one this delivery is assigned to."
                rows={data.nearest}
                rowKey={(depot) => depot.depot_id}
                empty="no depot in range"
                columns={[
                  { header: "Depot", cell: (d) => <span className="font-medium text-ink-900">{d.code} · {d.name}</span> },
                  { header: "Distance", cell: (d) => <span className="muted">{d.distance.toFixed(4)}</span> },
                  {
                    header: "State",
                    cell: (d) => (
                      <>
                        {d.assigned ? <Badge tone="ok">Assigned</Badge> : null}
                        {d.nearest && !d.assigned ? <Badge>Nearest</Badge> : null}
                      </>
                    ),
                  },
                ]}
              />
            </Card>

            <Card>
              <CardHead
                title="Picking slip"
                sub={`${data.packaging} · slot ${String(data.slot_hour).padStart(2, "0")}:00 · promised ${data.promised_on}`}
              />
              <CardBody>
                <DescriptionList
                  rows={[
                    ["Units", data.packing.units],
                    ["Per box", data.packing.per_box],
                    ["Labels (rounded up)", data.packing.boxes],
                    ["Sealed boxes (rounded down)", data.packing.full_boxes],
                    ["Loose units", data.packing.loose_units],
                  ]}
                />
              </CardBody>
            </Card>
          </div>
        </>
      )}
    </DataState>
  );
}
