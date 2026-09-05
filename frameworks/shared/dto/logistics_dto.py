"""DTOs for the logistics domain (depots, delivery sheets, dispatch boards and slot load).

Flat and JSON-able, like the rest of this package — and taking the USE CASE's answer rather than a
model, which is the one way these differ from their neighbours. The reason is not style: `inventory`
and `billing` answer with rows, so a DTO over a `Warehouse` is the whole job. This domain answers with
FIGURES the engine computed and DECISIONS made over them, and there is no row to serialise.

THE DECISIONS TRAVEL AND ARE NOT RE-DERIVED HERE. `is_routed_to_the_nearest`, `loose_units` and
`is_peak` are all things the use case worked out, and a client that had to compute them from the rest
of the payload would be a second implementation of the domain — the failure the BFF nets in
`shared/tests/` are written to catch, arriving one layer lower than they usually look.

THE NUMBERS TRAVEL AS NUMBERS. A slot goes out as `9` and a distance as `4.3117...`, not as `"09:00"`
and `"4.3"`. The page formats those because a person reads a page; a client that received strings
would have to parse them back to do anything at all, and formatting for a reader who is not there is
how an API acquires a display convention it can never change.
"""

from __future__ import annotations

from shared.usecases.logistics_usecases import (
    DeliverySheet,
    DepotSummary,
    DispatchEntry,
    SlotBand,
)


def depot_dict(depot: DepotSummary) -> dict[str, object]:
    """One depot with what is booked out of it."""
    return {
        "code": depot.code,
        "name": depot.name,
        "deliveries": depot.deliveries,
        "units": depot.units,
    }


def delivery_sheet_dict(sheet: DeliverySheet) -> dict[str, object]:
    """One delivery's sheet: the depot ranking, the packing slip and the routing verdict."""
    return {
        "delivery_id": sheet.delivery_id,
        "reference": sheet.reference,
        "depot": sheet.depot,
        "packaging": sheet.packaging,
        "slot_hour": sheet.slot_hour,
        "promised_on": sheet.promised_on,
        "nearest": [
            {
                "depot_id": row.depot_id,
                "code": row.code,
                "name": row.name,
                "distance": row.distance,
                "assigned": row.assigned,
                "nearest": row.nearest,
            }
            for row in sheet.nearest
        ],
        "packing": {
            "units": sheet.packing.units,
            "per_box": sheet.packing.per_box,
            "boxes": sheet.packing.boxes,
            "full_boxes": sheet.packing.full_boxes,
            "loose_units": sheet.packing.loose_units,
        },
        "is_routed_to_the_nearest": sheet.is_routed_to_the_nearest,
    }


def dispatch_entry_dict(entry: DispatchEntry) -> dict[str, object]:
    """One line of the dispatch board.

    Both dates are calendar days and they arrived that way: the selector normalises the computed one
    where the driver hands it over, because it is typed on PostgreSQL and ISO-8601 text on SQLite. A
    field whose shape changes with the engine underneath is a field no client can consume, and the
    fix belongs where the shape is decided rather than in every caller.
    """
    return {
        "delivery_id": entry.delivery_id,
        "reference": entry.reference,
        "promised_on": entry.promised_on,
        "leave_by": entry.leave_by,
    }


def slot_band_dict(band: SlotBand) -> dict[str, object]:
    """One booking with the load of the band it sits in."""
    return {
        "depot": band.depot,
        "slot_hour": band.slot_hour,
        "units": band.units,
        "band_units": band.band_units,
        "is_peak": band.is_peak,
    }
