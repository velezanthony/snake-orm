/**
 * The tick-box screen of ONE post, and the screen that made tagging idempotent.
 *
 * EACH BOX IS ONE REQUEST. Ticking calls `get_or_create`, so submitting the same box twice leaves
 * ONE bridge row instead of two; unticking asks `exists` and then deletes by the PAIR, never loading
 * the row it is about to discard. A submit-everything form would collapse both into "make the rows
 * match this list", which is a third operation neither surface offers.
 */

import { useParams } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { ButtonLink } from "@atoms/Button";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { Check } from "@atoms/Field";
import { useAction } from "~/core/hooks/useAction";
import { usePostTags } from "~/domains/taxonomy/viewmodels";

export function PostTagsPage() {
  const postId = Number(useParams().postId);

  const { state, toggle: run } = usePostTags(postId);
  const toggle = useAction(run);

  return (
    <>
      <PageHead
        title={`Tags of post ${postId}`}
        lede="The screen that made tagging idempotent. Each box is one request: ticking calls get_or_create, so submitting the same box twice leaves ONE bridge row instead of two; unticking asks exists and then deletes by the PAIR, never loading the row it is about to discard."
        actions={
          <ButtonLink size="sm" to={href("blog.detail", { postId: postId })}>
            ← The post
          </ButtonLink>
        }
      />

      {toggle.error !== null ? <Alert kind="error">{toggle.error}</Alert> : null}

      <DataState resource={state} loading="Reading the bridge…">
        {({ all, held }) => (
          <Card className="max-w-2xl">
            <CardHead title="Every tag" sub="Ticked means there is a bridge row. One box, one request." />
            <CardBody>
              <div className="flex flex-wrap gap-x-6 gap-y-2">
                {all.map((tag) => (
                  <Check
                    key={tag.id}
                    checked={held.has(tag.id)}
                    disabled={toggle.pending}
                    onChange={(event) => void toggle.run(tag.id, event.target.checked)}
                  >
                    {tag.name}
                  </Check>
                ))}
              </div>
            </CardBody>
          </Card>
        )}
      </DataState>
    </>
  );
}
