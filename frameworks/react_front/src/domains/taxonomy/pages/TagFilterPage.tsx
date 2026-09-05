/**
 * The page this domain exists for.
 *
 * Ticking two tags asks the engine to INTERSECT: requiring both is a condition on two DIFFERENT
 * bridge rows, so `tag_id = A AND tag_id = B` matches nothing and no WHERE expresses the question.
 * Naming one to exclude asks it to EXCEPT, which states the subtraction instead of handing the
 * planner a negated subquery.
 *
 * The selection lives in the URL, so a filter somebody found is a filter they can send.
 */

import { useSearchParams } from "react-router";

import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { DataTable } from "@organisms/DataTable";
import { Card, CardBody, CardHead } from "@molecules/Card";
import { Check, Field, Select } from "@atoms/Field";
import { Empty, Muted } from "@atoms/Text";
import { useFilteredPosts, useTags } from "~/domains/taxonomy/viewmodels";

function readIds(raw: string | null): number[] {
  if (raw === null || raw === "") return [];
  return raw.split(",").map(Number).filter(Number.isInteger);
}

export function TagFilterPage() {
  const [params, setParams] = useSearchParams();
  const selected = readIds(params.get("tags"));
  const withoutRaw = params.get("without");
  const without = withoutRaw === null || withoutRaw === "" ? undefined : Number(withoutRaw);

  const tags = useTags();

  // Whether the question can be asked at all is the viewmodel's call, and it is argued there: the
  // API refuses fewer than two tags with a 400, and rightly so.
  const { posts, enough } = useFilteredPosts(selected, without);

  function toggle(tagId: number, on: boolean) {
    const next = on ? [...selected, tagId] : selected.filter((id) => id !== tagId);
    const copy = new URLSearchParams(params);
    if (next.length === 0) copy.delete("tags");
    else copy.set("tags", next.join(","));
    setParams(copy);
  }

  return (
    <>
      <PageHead
        title="Filter posts by tag"
        lede="The page this domain exists for. Ticking two tags asks the engine to INTERSECT: requiring both is a condition on two DIFFERENT bridge rows, so tag_id = A AND tag_id = B matches nothing and no WHERE expresses the question. Naming one to exclude asks it to EXCEPT, which states the subtraction instead of handing the planner a negated subquery."
      />

      <DataState resource={tags} loading="Reading the tags…">
        {(all) => (
          <Card className="mb-6">
            <CardHead
              title="Narrow it"
              sub="Two or more tags intersect. Naming one to exclude subtracts it from the first."
            />
            <CardBody>
              <div className="flex flex-wrap gap-x-6 gap-y-2 pb-4">
                {all.map((tag) => (
                  <Check
                    key={tag.id}
                    checked={selected.includes(tag.id)}
                    onChange={(event) => toggle(tag.id, event.target.checked)}
                  >
                    {tag.name}
                  </Check>
                ))}
              </div>

              <Field id="without" label="Exclude one">
                <Select
                  id="without"
                  name="without"
                  value={without === undefined ? "" : String(without)}
                  onChange={(event) => {
                    const copy = new URLSearchParams(params);
                    if (event.target.value === "") copy.delete("without");
                    else copy.set("without", event.target.value);
                    setParams(copy);
                  }}
                >
                  <option value="">— exclude nothing —</option>
                  {all.map((tag) => (
                    <option key={tag.id} value={tag.id}>
                      {tag.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </CardBody>
          </Card>
        )}
      </DataState>

      {enough ? (
        <DataState resource={posts} loading="Asking the engine…">
          {(rows) =>
            rows.length === 0 ? (
              <Empty>No post carries all of those.</Empty>
            ) : (
              <DataTable
                label="Matching posts"
                caption="The posts the set operation came back with."
                rows={rows}
                rowKey={(post) => post.id}
                empty="nothing matched"
                columns={[
                  { header: "#", cell: (post) => <span className="muted">{post.id}</span> },
                  { header: "Title", cell: (post) => <span className="font-medium text-ink-900">{post.title}</span> },
                ]}
              />
            )
          }
        </DataState>
      ) : (
        <Muted>Tick at least two tags — or one, with something to exclude from it.</Muted>
      )}
    </>
  );
}
