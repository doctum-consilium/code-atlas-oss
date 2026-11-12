/**
 * Front settings. Only the API base URL is fixed at build time (VITE_API_URL); everything else
 * (sign-in mode, OIDC issuer and client, language) is read at start-up from GET /v1/public-config,
 * which needs no token and holds only public values.
 */
import type { components } from "./api/schema";

export type PublicConfig = components["schemas"]["PublicConfig"];

export const config = {
  api: import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8790",
} as const;

export async function loadPublicConfig(base: string = config.api, f: typeof fetch = fetch): Promise<PublicConfig> {
  const response = await f(`${base}/v1/public-config`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`public-config: HTTP ${response.status}`);
  return (await response.json()) as PublicConfig;
}
