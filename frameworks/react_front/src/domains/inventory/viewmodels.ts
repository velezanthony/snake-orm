/**
 * The inventory pages as hooks. The mirror of `apps/inventory/viewmodels.py`, 821 lines of it.
 *
 * This is the domain with the COMPOSITE key, so every hook here takes the pair in two halves — and
 * that is the thing worth having in one layer: get one half wrong and you have read a different row
 * that also exists.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import type { Page } from "~/core/http/shapes";
import { inventoryService } from "~/domains/inventory/service";
import type {
  Sku,
  StockMovement,
  StockReport,
  StockRow,
  Warehouse,
  WarehouseStats,
} from "~/domains/inventory/types";

/** `include(Stock.warehouse, Stock.sku)`: one SELECT with two JOINs, plus one COUNT for the pager. */
export function useStockPage(page: number): Resource<Page<StockRow>> {
  return useResource(() => inventoryService.stockPage(page), [page]);
}

export interface StockAlerts {
  rows: StockRow[];
  warehouseName: Map<number, string>;
  skuName: Map<number, string>;
}

/**
 * THREE statements: the read-only `LowStock` view, and the two catalogues its ids are named from.
 *
 * The view answers ids and nothing else, and a page that showed them raw would be a page nobody can
 * act on — which is why the naming happens here and not in a fourth query per row.
 */
export function useStockAlerts(): Resource<StockAlerts> {
  return useResource(async () => {
    const [rows, warehouses, skus] = await Promise.all([
      inventoryService.lowStock(),
      inventoryService.warehouses(),
      inventoryService.skus(),
    ]);
    return {
      rows,
      warehouseName: new Map(warehouses.map((w) => [w.id, `${w.code} · ${w.name}`])),
      skuName: new Map(skus.map((s) => [s.id, s.name])),
    };
  }, []);
}

export interface Catalogue {
  stats: WarehouseStats[];
  skus: Sku[];
}

/** What the inventory is made OF, as against what is IN it. Two statements, neither per row. */
export function useCatalogue(): Resource<Catalogue> {
  return useResource(async () => {
    const [stats, skus] = await Promise.all([inventoryService.stats(), inventoryService.skus()]);
    return { stats, skus };
  }, []);
}

export interface StockCatalogue {
  warehouses: Warehouse[];
  skus: Sku[];
}

/** What a stock row can point AT: the two things a pair is made of. */
export function useStockCatalogue(): Resource<StockCatalogue> {
  return useResource(async () => {
    const [warehouses, skus] = await Promise.all([
      inventoryService.warehouses(),
      inventoryService.skus(),
    ]);
    return { warehouses, skus };
  }, []);
}

export interface StockPair {
  stock: StockRow;
  movements: StockMovement[];
}

/** ONE pair and the to-many hanging off a foreign key TWO COLUMNS WIDE. */
export function useStockPair(warehouseId: number, skuId: number): Resource<StockPair> {
  return useResource(async () => {
    const [stock, movements] = await Promise.all([
      inventoryService.stockPair(warehouseId, skuId),
      inventoryService.movementsOf(warehouseId, skuId),
    ]);
    return { stock, movements };
  }, [warehouseId, skuId]);
}

export function useStockRow(warehouseId: number, skuId: number): Resource<StockRow> {
  return useResource(() => inventoryService.stockPair(warehouseId, skuId), [warehouseId, skuId]);
}

/**
 * One warehouse and what every line in it has been doing.
 *
 * The movements come back in a single select-in over a foreign key two columns wide — the hardest
 * relationship in these demos, because every parent binds two placeholders instead of one.
 */
export function useWarehouseSheet(warehouseId: number) {
  return useResource(async () => {
    const [warehouse, lines] = await Promise.all([
      inventoryService.warehouse(warehouseId),
      inventoryService.stockWithMovements(warehouseId),
    ]);
    return { warehouse, lines };
  }, [warehouseId]);
}

/** Five questions a plain `filter()` cannot answer, in five statements that do not grow. */
export function useStockReport(): Resource<StockReport> {
  return useResource(() => inventoryService.report(), []);
}

/**
 * The writes, and the verb IS the operation.
 *
 * `count` is a PUT — a physical count says the pair holds this many, whether or not the row was
 * there. `correct` is a PATCH — the record was wrong about a pair that exists. Two different
 * statements about the world, which is why they are two methods and not one with a flag.
 */
export const stockWrites = {
  count: (warehouseId: number, skuId: number, body: { on_hand: number }) =>
    inventoryService.countStock(warehouseId, skuId, body),
  correct: (warehouseId: number, skuId: number, body: { on_hand: number; reserved: number }) =>
    inventoryService.correctStock(warehouseId, skuId, body),
  remove: (warehouseId: number, skuId: number) => inventoryService.removeStock(warehouseId, skuId),
  receive: (warehouseId: number, skuId: number, units: number) =>
    inventoryService.receive(warehouseId, skuId, { units }),
  /** 409 if there are not that many: the rule refuses BEFORE writing. */
  ship: (warehouseId: number, skuId: number, units: number) =>
    inventoryService.ship(warehouseId, skuId, { units }),
  /** Reserves across the WAREHOUSE's whole stock in one statement. */
  reserve: (warehouseId: number, units: number) => inventoryService.reserve(warehouseId, { units }),
};
