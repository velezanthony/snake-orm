import { Fragment, type ReactNode } from "react";

/**
 * The label/value grid the detail pages use. `.dl` is a two-column grid in the stylesheet, so the
 * terms and the values have to be siblings — which is why this takes pairs and lays them out itself
 * rather than accepting arbitrary children that could nest them and quietly break the alignment.
 */
export function DescriptionList({ rows }: { rows: [ReactNode, ReactNode][] }) {
  return (
    <dl className="dl">
      {rows.map(([term, value], index) => (
        <Fragment key={index}>
          <dt>{term}</dt>
          <dd>{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
