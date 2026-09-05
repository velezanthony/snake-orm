/**
 * The topbar, and the same three groups the SSR templates carry: the brand, the developer tools and
 * the account.
 *
 * The SSR demos drive their `<select>`s with a shared `demo.js` that submits a hidden form for the
 * POST actions, because a link cannot POST. Here it is an `onChange` calling a service, which is
 * the same idea with the workaround removed.
 */

import { Link, useNavigate } from "react-router";

import { useAuth } from "~/domains/auth/useAuth";
import { BackendSwitcher } from "~/core/layout/BackendSwitcher";
import { ButtonLink } from "@atoms/Button";
import { InlineSelect } from "@atoms/Field";
import { href } from "~/config/href";
import { apiUrl, currentBackend } from "~/config/backends";

export function Topbar() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const backend = currentBackend();

  return (
    <header className="topbar">
      <div className="topbar-inner">
        <Link className="brand" to="/">
          <span className="brand-mark" aria-hidden="true">
            S
          </span>
          <span className="brand-name">SnakeORM · React</span>
        </Link>

        <div className="ml-auto flex items-center gap-2">
          <BackendSwitcher />

          <InlineSelect
            aria-label="Developer tools"
            value=""
            onChange={(event) => {
              if (event.target.value !== "") window.open(event.target.value, "_blank", "noopener");
            }}
          >
            <option value="" disabled>
              Dev
            </option>
            <option value={apiUrl("/api/posts")}>JSON API</option>
            <option value={`${backend.origin}${backend.page("/api/posts")}`}>
              The same page, rendered by {backend.label}
            </option>
          </InlineSelect>

          {user === null ? (
            <>
              <ButtonLink size="sm" to="/auth/login">
                Sign in
              </ButtonLink>
              <ButtonLink size="sm" variant="primary" to="/auth/register">
                Sign up
              </ButtonLink>
            </>
          ) : (
            <InlineSelect
              aria-label={`Account: ${user.username}`}
              value=""
              onChange={(event) => {
                // `void` and not `async`: a change handler must return void, and a promise handed to
                // one is a rejection nothing will ever catch.
                void (async () => {
                  const choice = event.target.value;
                  if (choice === "logout") {
                    await logout();
                    await navigate(href("auth.login"));
                  } else if (choice !== "") {
                    await navigate(choice);
                  }
                })();
              }}
            >
              <option value="" disabled>
                {user.username}
              </option>
              <option value="/posts/new">New post</option>
              <option value={`/auth/access/${user.id}`}>My access</option>
              <option value="logout">Sign out</option>
            </InlineSelect>
          )}
        </div>
      </div>
    </header>
  );
}
