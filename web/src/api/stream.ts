/**
 * Reading the answer stream (Server-Sent Events) of POST /v1/chat.
 *
 * EventSource can neither send an Authorization header nor make a POST: the fetch response is
 * therefore read piece by piece and cut into "event: … / data: …" blocks.
 */
import { t } from "../i18n";
import type { Chunk, Citation, QuestionRequest } from "./client";

export type ChatEvent =
  | {
      type: "chunks";
      conversation_id: string;
      model: string;
      provider: string;
      remote: boolean;
      chunks: Chunk[];
    }
  | { type: "token"; text: string }
  | { type: "done"; conversation_id: string; citations: Citation[]; invalid_citations: number[] }
  | { type: "error"; reason: string };

/** Cuts a complete or partial SSE text; returns the whole events and the rest. */
export function parseEvents(buffer: string): { events: ChatEvent[]; rest: string } {
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";
  const events: ChatEvent[] = [];
  for (const block of blocks) {
    let name = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) name = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trim());
    }
    if (!data.length) continue;
    try {
      const payload = JSON.parse(data.join("\n")) as Record<string, unknown>;
      events.push({ type: name, ...payload } as ChatEvent);
    } catch {
      continue;
    }
  }
  return { events, rest };
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Asks a question and yields the events as they arrive. */
export async function* ask(
  base: string,
  token: string | null,
  request: QuestionRequest,
  signal?: AbortSignal,
  f: typeof fetch = fetch,
): AsyncGenerator<ChatEvent> {
  const response = await f(`${base}/v1/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(request),
    signal: signal ?? null,
  });
  if (!response.ok || !response.body) {
    let detail = t("error.status", { status: response.status });
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* unreadable body: keep the status */
    }
    throw new ApiError(response.status, detail);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const { events, rest } = parseEvents(buffer);
    buffer = rest;
    yield* events;
  }
  yield* parseEvents(buffer + "\n\n").events;
}
