/**
 * A tag is a name inside a group, and optionally a place in the TREE.
 *
 * There is no page to rename or delete one, and that is the domain's statement rather than a form
 * nobody wrote: a tag is a name that rows point at, so renaming it rewrites what every post carrying
 * it says.
 */

import * as fields from "~/core/lib/form";
import { useNavigate } from "react-router";

import { href } from "~/config/href";

import { Alert } from "@molecules/Alert";
import { DataState } from "@organisms/DataState";
import { PageHead } from "@molecules/PageHead";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardForm } from "@molecules/Card";
import { Field, Input, Select } from "@atoms/Field";
import { FormActions } from "@molecules/FormActions";
import { useAction } from "~/core/hooks/useAction";
import { taxonomyService } from "~/domains/taxonomy/service";
import { useTagCatalogue } from "~/domains/taxonomy/viewmodels";

export function TagCreatePage() {
  const navigate = useNavigate();
  const catalogue = useTagCatalogue();

  const create = useAction(async (form: HTMLFormElement) => {
    const data = new FormData(form);
    const parent = fields.text(data, "parent_id");
    await taxonomyService.createTag({
      name: fields.text(data, "name"),
      group_id: fields.number(data, "group_id"),
      // An empty option is "no parent" — a ROOT tag — and not a zero the API would have to guess at.
      parent_id: parent === "" ? null : Number(parent),
    });
    await navigate(href("taxonomy.list"));
  });

  return (
    <>
      <PageHead
        title="New tag"
        lede="A tag is a name inside a group, and optionally a place in the TREE. There is no page to rename or delete one, and that is the domain's statement rather than a form nobody wrote: a tag is a name that rows point at, so renaming it rewrites what every post carrying it says."
      />

      {create.error !== null ? <Alert kind="error">{create.error}</Alert> : null}

      <DataState resource={catalogue} loading="Reading the groups…">
        {({ groups, tags }) => (
          <Card className="max-w-md">
            <CardForm onSubmit={(form) => void create.run(form)}>
              <Field id="name" label="Name">
                <Input type="text" id="name" name="name" autoFocus />
              </Field>

              <Field id="group_id" label="Group">
                <Select id="group_id" name="group_id" defaultValue={groups[0]?.id}>
                  {groups.map((group) => (
                    <option key={group.id} value={group.id}>
                      {group.name}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field id="parent_id" label="Parent (optional)">
                <Select id="parent_id" name="parent_id" defaultValue="">
                  <option value="">— a root tag —</option>
                  {tags.map((tag) => (
                    <option key={tag.id} value={tag.id}>
                      {tag.name}
                    </option>
                  ))}
                </Select>
              </Field>

              <FormActions>
                <Button type="submit" disabled={create.pending}>
                  {create.pending ? "Creating…" : "Create tag"}
                </Button>
                <ButtonLink to={href("taxonomy.list")}>Cancel</ButtonLink>
              </FormActions>
            </CardForm>
          </Card>
        )}
      </DataState>
    </>
  );
}
