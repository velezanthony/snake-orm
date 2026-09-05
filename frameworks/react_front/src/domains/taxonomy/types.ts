/**
 * Tags, their groups and their place in the tree.
 */

export interface TagGroup {
  id: number;
  name: string;
}

export interface Tag {
  id: number;
  name: string;
  group_id: number;
  parent_id: number | null;
}

/** A tag with the path back to its root and the section hanging underneath it. */
export interface TagTree {
  breadcrumb: Tag[];
  branch: Tag[];
}
