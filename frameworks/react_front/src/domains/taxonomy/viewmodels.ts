/**
 * The taxonomy pages as hooks. The mirror of `apps/taxonomy/viewmodels.py`.
 */

import { useResource, type Resource } from "~/core/hooks/useResource";
import { taxonomyService } from "~/domains/taxonomy/service";
import type { Tag, TagGroup, TagTree } from "~/domains/taxonomy/types";
import type { Post } from "~/domains/blog/types";

export interface TagCatalogue {
  groups: TagGroup[];
  tags: Tag[];
}

/**
 * TWO statements for the whole screen, and the grouping happens once HERE.
 *
 * Walking `group.tags` instead would be one query per group — an N+1 inside the renderer, where no
 * test counts. Which is the same argument the SSR page makes, and the reason it belongs in this
 * layer rather than inside a component.
 */
export function useTagCatalogue(): Resource<TagCatalogue> {
  return useResource(async () => {
    const [groups, tags] = await Promise.all([taxonomyService.groups(), taxonomyService.tags()]);
    return { groups, tags };
  }, []);
}

export function useTags(): Resource<Tag[]> {
  return useResource(() => taxonomyService.tags(), []);
}

/** The path back to the root and the section hanging underneath: two WITH RECURSIVE, any depth. */
export function useTagTree(tagId: number): Resource<TagTree> {
  return useResource(() => taxonomyService.tree(tagId), [tagId]);
}

/**
 * The set operation, and the page does NOT ask until it can.
 *
 * The API refuses fewer than two tags with a 400, and it is right to: "the posts of one tag" is a
 * different question with an operation of its own. Firing a request known to be refused and
 * rendering the refusal as an error would be this client inventing a failure.
 */
export function useFilteredPosts(tagIds: number[], without: number | undefined): {
  posts: Resource<Post[]>;
  enough: boolean;
} {
  const enough = tagIds.length >= 2 || (without !== undefined && tagIds.length >= 1);
  const posts = useResource(
    () => (enough ? taxonomyService.filterPosts(tagIds, without) : Promise.resolve([])),
    [tagIds.join(","), without, enough],
  );
  return { posts, enough };
}

/** The tick-box screen: every tag, and the ones this post holds. ONE box is ONE request. */
export function usePostTags(postId: number) {
  const state = useResource(async () => {
    const [all, mine] = await Promise.all([taxonomyService.tags(), taxonomyService.tagsOf(postId)]);
    return { all, held: new Set(mine.map((tag) => tag.id)) };
  }, [postId]);

  return {
    state,
    toggle: async (tagId: number, on: boolean) => {
      if (on) await taxonomyService.tagPost(postId, tagId);
      else await taxonomyService.untag(postId, tagId);
      // Re-read rather than flip the box locally: the server decides whether the bridge row exists,
      // and a box that disagrees with it is a lie the reader has no way to spot.
      state.reload();
    },
  };
}
