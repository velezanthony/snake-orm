/**
 * The sign-up page. It does NOT sign you in afterwards, and that is not an omission: the three
 * Python demos redirect to the login form, and a fourth client that behaved differently would be a
 * fourth answer to a question the domain has already answered.
 */

import * as fields from "~/core/lib/form";
import { useNavigate } from "react-router";

import { href } from "~/config/href";

import { useAuth } from "~/domains/auth/useAuth";
import { Alert } from "@molecules/Alert";
import { PageHead } from "@molecules/PageHead";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardForm } from "@molecules/Card";
import { Field, Input } from "@atoms/Field";
import { FormActions } from "@molecules/FormActions";
import { useAction } from "~/core/hooks/useAction";

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();

  const signUp = useAction(async (registration: { username: string; email: string; password: string }) => {
    await register(registration);
    await navigate(href("auth.login"), { replace: true });
  });

  return (
    <>
      <PageHead
        title="Create account"
        lede="Username and email are unique. The password is stored hashed, never in the clear."
      />

      {signUp.error !== null ? <Alert kind="error">{signUp.error}</Alert> : null}

      <Card className="max-w-md">
        <CardForm
          onSubmit={(form) => {
            const data = new FormData(form);
            void signUp.run({
              username: fields.text(data, "username"),
              email: fields.text(data, "email"),
              password: fields.secret(data, "password"),
            });
          }}
        >
          <Field id="username" label="Username">
            <Input type="text" id="username" name="username" autoFocus autoComplete="username" />
          </Field>

          <Field id="email" label="Email">
            <Input type="email" id="email" name="email" autoComplete="email" />
          </Field>

          <Field id="password" label="Password">
            <Input type="password" id="password" name="password" autoComplete="new-password" />
          </Field>

          <FormActions>
            <Button type="submit" disabled={signUp.pending}>
              {signUp.pending ? "Creating…" : "Sign up"}
            </Button>
            <ButtonLink to={href("auth.login")}>I already have one</ButtonLink>
          </FormActions>
        </CardForm>
      </Card>
    </>
  );
}
