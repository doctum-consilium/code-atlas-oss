/** Typed API client, generated from contract/openapi.yaml (src/api/schema.d.ts, `npm run contract`). */
import createClient, { type Middleware } from "openapi-fetch";

import type { Session } from "../auth";
import { config } from "../config";
import { t } from "../i18n";
import type { components, paths } from "./schema";

export type Chunk = components["schemas"]["ChunkOut"];
export type Filters = components["schemas"]["Filters"];
export type Models = components["schemas"]["Models"];
export type Repo = components["schemas"]["RepoOut"];
export type Facets = components["schemas"]["Facets"];
export type Citation = components["schemas"]["Citation"];
export type ConversationSummary = components["schemas"]["ConversationSummary"];
export type Conversation = components["schemas"]["Conversation"];
export type FileContent = components["schemas"]["FileOut"];
export type IndexStatus = components["schemas"]["IndexStatus"];
export type Me = components["schemas"]["Me"];
export type QuestionRequest = components["schemas"]["QuestionRequest"];

export type Api = ReturnType<typeof createApi>;

export function emptyFilters(): Filters {
  return { repos: [], languages: [], types: [], owners: [] };
}

/** Readable message for an API error answer. */
export function reason(error: unknown, status?: number): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = error.detail;
    if (typeof detail === "string") return detail;
  }
  if (status === 429) return t("error.tooMany");
  return status ? t("error.status", { status }) : t("error.unreachable");
}

export function createApi(session: Session, base: string = config.api, f: typeof fetch = fetch) {
  const client = createClient<paths>({ baseUrl: base, fetch: f });
  const bearer: Middleware = {
    onRequest({ request }) {
      const value = session.token();
      if (value) request.headers.set("Authorization", `Bearer ${value}`);
      return request;
    },
    onResponse({ response }) {
      if (response.status === 401) session.forget();
      return response;
    },
  };
  client.use(bearer);
  return client;
}
