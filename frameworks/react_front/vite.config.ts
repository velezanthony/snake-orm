import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import type { IncomingMessage, ServerResponse } from "node:http";
import { fileURLToPath } from "node:url";
import { defineConfig, type ProxyOptions } from "vite";

import { BACKENDS, type BackendConfig } from "./src/config/backends.ts";

/**
 * The dev server, and the proxy that makes an `HttpOnly` session cookie work against three origins.
 *
 * `src/config/backends.ts` argues the why at length; the short version is that the browser must
 * believe it is talking to ONE origin, so every backend is mounted under a prefix of this server and
 * the prefix is stripped on the way out. The config module is imported rather than copied so the
 * prefixes cannot drift: the client builds its URLs from the same table this proxy is keyed on.
 *
 * ---------------------------------------------------------------------------------------------
 * AND THE COOKIE JAR HAS TO BE ISOLATED, NOT JUST SCOPED. This was found by looking, not by
 * reasoning: `/api/auth/me` answered 401 immediately after a successful login, and the request
 * carried TWO cookies called `sessionid` — one this proxy had set and one belonging to a completely
 * different application the same developer runs on `localhost`. Whichever the server's parser keeps
 * is the one that wins, and here it kept the stranger's.
 *
 * `localhost` is a SHARED cookie namespace. Every project on the machine writes into it, and
 * `sessionid` is what Django calls its session everywhere — so this is not an unlucky coincidence,
 * it is the default outcome for anyone with two Django projects. `cookiePathRewrite` alone does not
 * save you: a cookie already set at `Path=/` is sent to every path underneath it, including ours.
 *
 * So the proxy RENAMES. Each backend's cookies are stored under a prefix of their own on the way
 * back, and on the way out only that prefix is forwarded, with the prefix stripped off. The three
 * backends cannot see each other's session — Flask and Starlette both call theirs `session` — and
 * nothing else on `localhost` can reach them either. The Python side is untouched and never learns
 * that any of this happened.
 */

/** The prefix a backend's cookies are stored under in the browser. Letters only: it is a cookie name. */
function jarPrefix(backend: BackendConfig): string {
  return `snake_${backend.id}__`;
}

/** `a=1; b=2` → the pairs, with the parsing done once. */
function parseCookies(header: string): [string, string][] {
  return header
    .split(";")
    .map((piece) => piece.trim())
    .filter((piece) => piece !== "")
    .map((piece) => {
      const eq = piece.indexOf("=");
      return eq === -1 ? ([piece, ""] as [string, string]) : ([piece.slice(0, eq), piece.slice(eq + 1)] as [string, string]);
    });
}

function proxyFor(backend: BackendConfig): ProxyOptions {
  const prefix = jarPrefix(backend);

  return {
    target: backend.origin,
    changeOrigin: true,
    rewrite: (path: string) => path.slice(backend.prefix.length) || "/",

    configure(proxy) {
      // Outbound: forward ONLY this backend's jar, with the prefix taken off, so the server sees
      // exactly the cookie names it set and nothing else the browser happens to be holding.
      proxy.on("proxyReq", (proxyReq, req: IncomingMessage) => {
        const header = req.headers.cookie;
        if (header === undefined) return;
        const mine = parseCookies(header)
          .filter(([name]) => name.startsWith(prefix))
          .map(([name, value]) => `${name.slice(prefix.length)}=${value}`);
        if (mine.length === 0) proxyReq.removeHeader("cookie");
        else proxyReq.setHeader("cookie", mine.join("; "));
      });

      // Inbound: store under the prefix, scoped to this backend's path. `Domain` is dropped because
      // the server named an origin the browser is not talking to; a host-only cookie is correct here.
      proxy.on("proxyRes", (proxyRes, _req: IncomingMessage, _res: ServerResponse) => {
        const cookies = proxyRes.headers["set-cookie"];
        if (cookies === undefined) return;
        proxyRes.headers["set-cookie"] = cookies.map((cookie) => {
          const [pair, ...attributes] = cookie.split(";");
          const eq = (pair ?? "").indexOf("=");
          if (eq === -1) return cookie;
          const renamed = `${prefix}${pair!.slice(0, eq)}=${pair!.slice(eq + 1)}`;
          const kept = attributes
            .map((attribute) => attribute.trim())
            .filter((attribute) => {
              const key = attribute.split("=")[0]?.toLowerCase();
              return key !== "path" && key !== "domain";
            });
          return [renamed, `Path=${backend.prefix}`, ...kept].join("; ");
        });
      });
    },
  };
}

const proxy = Object.fromEntries(
  Object.values(BACKENDS).map((backend) => [backend.prefix, proxyFor(backend)]),
);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // The SAME four the tsconfig declares. Two lists that have to agree is a list that will not, so
    // the shape is kept identical and short enough to read as one thing.
    alias: {
      "~": fileURLToPath(new URL("./src", import.meta.url)),
      "@atoms": fileURLToPath(new URL("./src/core/ui/atoms", import.meta.url)),
      "@molecules": fileURLToPath(new URL("./src/core/ui/molecules", import.meta.url)),
      "@organisms": fileURLToPath(new URL("./src/core/ui/organisms", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy,
  },
});
