/**
 * statements, covered, branches, covered branches, partial.
 * @typedef {[number, number, number, number, number]} Row
 */

/**
 * @typedef {object} Snapshot
 * @property {string} at Timestamp, and also the filename.
 * @property {string[]} [suites] Which suites produced it. Snapshots of different suites are not
 *   comparable: the number moved because the instrument did.
 * @property {Record<string, Row>} domains
 * @property {Record<string, Row>} files
 * @property {Record<string, Row>} functions
 */

/**
 * @template T
 * @typedef {object} Column
 * @property {string} head
 * @property {(row: T) => string} cell
 */

export {};
