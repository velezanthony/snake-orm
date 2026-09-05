/**
 * The engagement pages as hooks. The mirror of `apps/engagement/viewmodels.py`.
 */

import { useState } from "react";

import { useResource, type Resource } from "~/core/hooks/useResource";
import { blogService } from "~/domains/blog/service";
import type { Post } from "~/domains/blog/types";
import { engagementService } from "~/domains/engagement/service";
import type { Comment, Reaction, Visit } from "~/domains/engagement/types";

export interface TrafficBoard {
  rows: Post[];
  total: number;
}

/**
 * ONE statement for the whole board, whatever the size of the visits table.
 *
 * The counter is a COLUMN on the post, kept by a TRIGGER rather than by the ORM, so a listing of
 * every post costs one query — where counting `post.visits` per row would be an N+1 over the demo's
 * biggest table. The ordering and the total are done over rows that have ALREADY ARRIVED, which is
 * the same decision `engagement_viewmodels.traffic_board` makes: the whole board is on the rows the
 * first request brought, and a second trip to sort four hundred integers answers nothing new.
 */
export function useTrafficBoard(): Resource<TrafficBoard> {
  return useResource(async () => {
    const { posts } = await blogService.list();
    const rows = [...posts].sort((a, b) => b.visit_count - a.visit_count);
    return { rows, total: rows.reduce((sum, post) => sum + post.visit_count, 0) };
  }, []);
}

export interface EngagementSheet {
  post: Post;
  comments: Comment[];
  reactions: Reaction[];
  visits: Visit[];
}

/**
 * One post's comments, reactions and visits, plus the counter as the ENGINE has it.
 *
 * `counted` holds what came back from recording a visit and NOT a number this client added up.
 * `visit_count` is moved by a trigger underneath the object the request was holding, so incrementing
 * locally would be the page guessing at the one figure it cannot compute.
 */
export function useEngagementSheet(postId: number) {
  const [counted, setCounted] = useState<number | null>(null);

  const sheet: Resource<EngagementSheet> = useResource(async () => {
    const [post, comments, reactions, visits] = await Promise.all([
      blogService.get(postId),
      engagementService.comments(postId),
      engagementService.reactions(postId),
      engagementService.visits(postId),
    ]);
    return { post, comments, reactions, visits };
  }, [postId]);

  return {
    sheet,
    counted,
    recordVisit: async () => {
      const tally = await engagementService.recordVisit(postId);
      setCounted(tally.visit_count);
    },
  };
}
