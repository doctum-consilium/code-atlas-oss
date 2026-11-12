import { describe, expect, it } from "vitest";

import { reason } from "../src/api/client";
import { ApiError, ask, parseEvents } from "../src/api/stream";
import { citationNumber, linkCitations } from "../src/citations";
import { loadPublicConfig } from "../src/config";
import { cspPolicy } from "../vite.config";
import { fakeFetch, fakeSession, json, on, sseStream, testApi } from "./helpers";

describe("citations", () => {
  it("links valid numbers and marks the others", () => {
    expect(linkCitations("A [1] and B [2][7].", 2)).toBe("A [\\[1\\]](#chunk-1) and B [\\[2\\]](#chunk-2)[7]⁇.");
  });
  it("leaves code alone", () => {
    expect(linkCitations("see `tab[1]` and\n```\nx[2]\n```\n[1]", 2)).toBe(
      "see `tab[1]` and\n```\nx[2]\n```\n[\\[1\\]](#chunk-1)",
    );
  });
  it("does not double an existing Markdown link", () => {
    expect(linkCitations("[1](http://x)", 3)).toBe("[1](http://x)");
  });
  it("reads the number back from an internal link", () => {
    expect(citationNumber("#chunk-3")).toBe(3);
    expect(citationNumber("https://x")).toBeNull();
    expect(citationNumber(undefined)).toBeNull();
    expect(citationNumber("#chunk-x")).toBeNull();
  });
});

describe("SSE stream", () => {
  it("cuts whole events and keeps the rest", () => {
    const { events, rest } = parseEvents('event: token\ndata: {"text":"a"}\n\nevent: done\nda');
    expect(events).toEqual([{ type: "token", text: "a" }]);
    expect(rest).toBe("event: done\nda");
  });
  it("skips a block without data or with unreadable data", () => {
    expect(parseEvents("event: x\n\nevent: y\ndata: {not json\n\n").events).toEqual([]);
  });
  it("reads a stream cut anywhere and sends the token", async () => {
    const { f, requests } = fakeFetch(() =>
      sseStream([
        ["chunks", { conversation_id: "c", model: "m", provider: "local", remote: false, chunks: [] }],
        ["token", { text: "Hello " }],
        ["token", { text: "é [1]" }],
        ["done", { conversation_id: "c", citations: [], invalid_citations: [] }],
      ]),
    );
    const received = [];
    for await (const e of ask("http://api.test", "tk", { question: "q", mode: "local" }, undefined, f)) received.push(e);
    expect(received.map((e) => e.type)).toEqual(["chunks", "token", "token", "done"]);
    expect(
      received
        .filter((e) => e.type === "token")
        .map((e) => e.text)
        .join(""),
    ).toBe("Hello é [1]");
    expect(requests[0]?.headers.get("Authorization")).toBe("Bearer tk");
    expect(await requests[0]?.json()).toEqual({ question: "q", mode: "local" });
  });
  it("gives the reason of a refusal", async () => {
    const { f } = fakeFetch(() => json({ detail: "refused: alias not on the ZDR list" }, 409));
    const events = ask("http://api.test", null, { question: "q", mode: "gateway" }, undefined, f);
    await expect(events.next()).rejects.toEqual(new ApiError(409, "refused: alias not on the ZDR list"));
  });
  it("keeps the status when the body is unreadable", async () => {
    const { f, requests } = fakeFetch(() => new Response("not json", { status: 502 }));
    await expect(ask("http://api.test", null, { question: "q", mode: "local" }, undefined, f).next()).rejects.toThrow(
      "Error 502",
    );
    expect(requests[0]?.headers.get("Authorization")).toBeNull();
  });
});

describe("client", () => {
  it("adds the token and forgets the session on 401", async () => {
    const session = fakeSession();
    const { api, requests } = testApi(session, on("GET", "/v1/me", () => json({ detail: "not authenticated" }, 401)));
    const { error, response } = await api.GET("/v1/me");
    expect(requests[0]?.headers.get("Authorization")).toBe("Bearer test-token");
    expect(response.status).toBe(401);
    expect(reason(error, response.status)).toBe("not authenticated");
    expect(session.forget).toHaveBeenCalled();
  });
  it("sends nothing without a token", async () => {
    const { api, requests } = testApi(fakeSession(false), on("GET", "/healthz", () => json({ status: "ok" })));
    await api.GET("/healthz");
    expect(requests[0]?.headers.get("Authorization")).toBeNull();
  });
  it("gives readable reasons", () => {
    expect(reason(null, 429)).toMatch(/try again/);
    expect(reason({ detail: [{ msg: "x" }] }, 422)).toBe("Error 422");
    expect(reason(undefined)).toBe("API unreachable");
  });
});

describe("public config", () => {
  it("is read without a token", async () => {
    const { f, requests } = fakeFetch(
      on("GET", "/v1/public-config", () => json({ auth_mode: "token", language: "fr", oidc: null })),
    );
    expect(await loadPublicConfig("http://api.test", f)).toEqual({ auth_mode: "token", language: "fr", oidc: null });
    expect(requests[0]?.headers.get("Authorization")).toBeNull();
  });
  it("fails on an error status", async () => {
    const { f } = fakeFetch();
    await expect(loadPublicConfig("http://api.test", f)).rejects.toThrow("HTTP 404");
  });
});

describe("CSP", () => {
  it("only allows the API by default, and forbids frames", () => {
    const csp = cspPolicy("http://127.0.0.1:8790");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:8790;");
    expect(csp).toContain("script-src 'self'");
    expect(csp).toContain("frame-src 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).not.toContain("unsafe-eval");
  });
  it("adds the extra origins given at build time", () => {
    const csp = cspPolicy("http://127.0.0.1:8790", "https://sso.example.org/realms/dev, https://other.example.org");
    expect(csp).toContain("connect-src 'self' http://127.0.0.1:8790 https://sso.example.org https://other.example.org;");
  });
});
