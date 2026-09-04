/**
 * The two shapes several domains answer with, and that belong to none of them.
 */

// --- pagination ---------------------------------------------------------------------------------

/** The page envelope the paginated endpoints answer with (`/page` on orders, invoices and stock). */
export interface Page<T> {
  rows: T[];
  /** 1-based. */
  page: number;
  /** How many pages there are in total, not how many rows. */
  pages: number;
  total: number;
}

// --- the tabular shape the lab and the reports answer with ---------------------------------------

/**
 * A titled table with its own provenance note.
 *
 * The six lab endpoints all answer in exactly this shape, and so does half of every report page.
 * That is not a coincidence the client is exploiting: the SSR templates say a number with no
 * provenance teaches nothing, so every table in those pages carries the line about which part of
 * the ORM produced it. Once the note travels WITH the table, one component can render all of them.
 */
export interface Section {
  title: string;
  note: string;
  columns: string[];
  /** Positional, matching `columns`. Cells are whatever the domain put there. */
  rows: unknown[][];
}

export interface SectionsResponse {
  sections: Section[];
}
