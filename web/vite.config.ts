/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

/**
 * Strict CSP: the front only talks to the API (and to the extra origins given at build time), and is
 * shown in no frame.
 *
 * - connect-src: ``'self'`` and the API. In OIDC mode the issuer is only known at runtime (GET
 *   /v1/public-config), yet the browser must reach its discovery and token endpoints: list its
 *   origin in VITE_CSP_EXTRA_CONNECT (space- or comma-separated origins).
 * - frame-src ``'none'``: sign-in goes through a popup (a top-level window, not governed by
 *   frame-src) and silent renewal uses the refresh token through fetch (connect-src), so no
 *   iframe is ever needed. An issuer that issues no refresh token would need its origin here.
 */
export function cspPolicy(api: string, extraConnect = ""): string {
  const extra = extraConnect
    .split(/[\s,]+/)
    .filter(Boolean)
    .map((origin) => new URL(origin).origin);
  const connect = [...new Set(["'self'", api, ...extra])].join(" ");
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    `connect-src ${connect}`,
    "frame-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
    "object-src 'none'",
    "frame-ancestors 'none'",
  ].join("; ");
}

/** Copies the CSP into the built HTML (``frame-ancestors`` only works as a header). */
function cspInHtml(csp: string): Plugin {
  const meta = csp.replace("; frame-ancestors 'none'", "");
  return {
    name: "csp-in-html",
    apply: "build",
    transformIndexHtml: (html) =>
      html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${meta}" />`),
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const api = env.VITE_API_URL ?? "http://127.0.0.1:8790";
  const csp = cspPolicy(api, env.VITE_CSP_EXTRA_CONNECT ?? "");
  return {
    plugins: [react(), cspInHtml(csp)],
    preview: {
      headers: {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
        "Cross-Origin-Opener-Policy": "same-origin-allow-popups", // the OIDC sign-in popup must reach back
      },
    },
    server: { headers: { "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer" } },
    build: {
      sourcemap: false,
      target: "es2022",
      rollupOptions: { input: { index: "index.html", signin: "signin.html" } },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./tests/setup.ts"],
      include: ["tests/**/*.test.{ts,tsx}"],
      coverage: {
        provider: "v8",
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/main.tsx", "src/api/schema.d.ts"],
        thresholds: { lines: 80, functions: 80, branches: 70, statements: 80 },
      },
    },
  };
});
