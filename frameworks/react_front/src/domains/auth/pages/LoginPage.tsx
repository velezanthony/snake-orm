/**
 * The sign-in page, and the same one `/auth/login/` renders — down to the seeded credentials in the
 * lede, because a reader arriving cold needs them and the Django template gives them.
 *
 * The form is UNCONTROLLED. React's own docs stopped recommending a `useState` per input for a form
 * that only reads its values on submit, and a login form is that shape exactly: nothing here
 * validates as you type, so a re-render per keystroke buys nothing at all.
 */

import * as fields from "~/core/lib/form";
import { useLocation, useNavigate } from "react-router";

import { href } from "~/config/href";

import { useAuth } from "~/domains/auth/useAuth";
import { Alert } from "@molecules/Alert";
import { PageHead } from "@molecules/PageHead";
import { Button, ButtonLink } from "@atoms/Button";
import { Card, CardForm } from "@molecules/Card";
import { Field, Input } from "@atoms/Field";
import { FormActions } from "@molecules/FormActions";
import { Code } from "@atoms/Text";
import { useAction } from "~/core/hooks/useAction";

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Where the guard bounced them from, if it did. Falling back to the post list is the same
  // destination `apps/auth/views.login` redirects to.
  const from = (location.state as LocationState | null)?.from ?? "/";

  const signIn = useAction(async (credentials: { username: string; password: string }) => {
    await login(credentials);
    await navigate(from, { replace: true });
  });

  return (
    <>
      <PageHead
        title="Sign in"
        lede={
          <>
            Seeded account: <Code>demo1</Code> / <Code>test1234</Code>.
          </>
        }
      />

      {signIn.error !== null ? <Alert kind="error">{signIn.error}</Alert> : null}

      <Card className="max-w-md">
        <CardForm
          onSubmit={(form) => {
            const data = new FormData(form);
            void signIn.run({
              username: fields.text(data, "username"),
              password: fields.secret(data, "password"),
            });
          }}
        >
          <Field id="username" label="Username">
            <Input type="text" id="username" name="username" autoFocus autoComplete="username" />
          </Field>

          <Field id="password" label="Password">
            <Input type="password" id="password" name="password" autoComplete="current-password" />
          </Field>

          <FormActions>
            <Button type="submit" disabled={signIn.pending}>
              {signIn.pending ? "Signing in…" : "Sign in"}
            </Button>
            <ButtonLink to={href("auth.register")}>Create account</ButtonLink>
          </FormActions>
        </CardForm>
      </Card>
    </>
  );
}
