import { vi } from "vitest";

import { createApi, type Chunk } from "../src/api/client";
import type { AuthMode, Session } from "../src/auth";

export type Route = (request: Request) => Response | Promise<Response> | undefined;

/** Fake fetch: each route answers or passes; requests are kept. */
export function fakeFetch(...routes: Route[]) {
  const requests: Request[] = [];
  const f = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = input instanceof Request ? input : new Request(input, init);
    requests.push(request.clone());
    for (const route of routes) {
      const response = await route(request);
      if (response) return response;
    }
    return json({ detail: "unknown route" }, 404);
  });
  return { f: f as unknown as typeof fetch, requests };
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function on(method: string, path: string, answer: () => Response): Route {
  return (r) => (r.method === method && new URL(r.url).pathname === path ? answer() : undefined);
}

export type FakeSession = Session & {
  forget: ReturnType<typeof vi.fn>;
  signIn: ReturnType<typeof vi.fn>;
  reauthenticate: ReturnType<typeof vi.fn>;
  signOut: ReturnType<typeof vi.fn>;
};

export function fakeSession(connected = true, mode: AuthMode = "oidc"): FakeSession {
  const listeners = new Set<(c: boolean) => void>();
  const state = { connected };
  const set = (value: boolean) => {
    state.connected = value;
    for (const l of listeners) l(value);
  };
  const session = {
    mode,
    get connected() {
      return state.connected;
    },
    token: () => (state.connected ? "test-token" : null),
    subscribe: (l: (c: boolean) => void) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    forget: vi.fn(() => {
      set(false);
    }),
    signIn: vi.fn(() => {
      set(true);
      return Promise.resolve();
    }),
    reauthenticate: vi.fn(() => Promise.resolve()),
    signOut: vi.fn(() => {
      set(false);
      return Promise.resolve();
    }),
  };
  return session;
}

/** Number of entries in browser storage: read only to check that it stays empty. */
export function browserStorageSize(): number {
  // eslint-disable-next-line no-restricted-properties -- checking that nothing is stored
  return window.localStorage.length + window.sessionStorage.length;
}

export function testApi(session: Session, ...routes: Route[]) {
  const { f, requests } = fakeFetch(...routes);
  return { api: createApi(session, "http://api.test", f), requests, f };
}

export function chunk(n: number, extra: Partial<Chunk> = {}): Chunk {
  return {
    id: n,
    repo: "acme/api",
    path: `app/f${n}.py`,
    language: "python",
    type: "code",
    kind: "function",
    symbol: `function_${n}`,
    line_start: 10,
    line_end: 12,
    text: `def function_${n}():\n    return ${n}\n`,
    url: `https://git.example.org/acme/api/blob/abc/app/f${n}.py#L10-L12`,
    score: 1,
    local_only: false,
    ranks: {},
    ...extra,
  };
}

export function sseStream(events: Array<[string, unknown]>, pieceSize = 7): Response {
  const text = events.map(([name, d]) => `event: ${name}\ndata: ${JSON.stringify(d)}\n\n`).join("");
  const pieces = text.match(new RegExp(`[\\s\\S]{1,${pieceSize}}`, "g")) ?? [];
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      const encoder = new TextEncoder();
      for (const p of pieces) c.enqueue(encoder.encode(p));
      c.close();
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}
