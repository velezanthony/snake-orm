/// <reference path="./types.js" />

import { DATA_DIR, MANIFEST } from "./constants.js";

/** @type {(name: string) => Promise<any>} */
const read = async (name) => {
  const response = await fetch(`${DATA_DIR}/${name}`);
  if (!response.ok) throw new Error(`${name}: ${response.status}`);
  return response.json();
};

/** @type {() => Promise<Snapshot[]>} */
export const load = async () => {
  /** @type {{snapshots: string[]}} */
  const listed = await read(MANIFEST);
  return Promise.all(listed.snapshots.map(read));
};
