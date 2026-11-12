import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../src/App";
import { Boot } from "../src/Boot";
import { FiltersPanel } from "../src/components/FiltersPanel";
import { ModelPicker } from "../src/components/ModelPicker";
import { Repos } from "../src/components/Repos";
import { SourcePanel } from "../src/components/SourcePanel";
import { setLanguage } from "../src/i18n";
import { browserStorageSize, chunk, fakeFetch, fakeSession, json, on, sseStream, testApi, type Route } from "./helpers";

const ME = { subject: "s", email: "dev@example.org", client: "code-atlas-web", admin: true };
const FACETS = { repos: ["acme/api"], languages: ["python"], types: ["code", "doc"], owners: ["acme"] };
const NO_FILTERS = { repos: [], languages: [], types: [], owners: [] };
const ALLOWED_MODEL = {
  alias: "zdr-coder-30b",
  provider: "provider-a",
  allowed: true,
  reason: "ZDR",
  verified_on: "2026-11-12",
  source: "s",
};
const MODELS = {
  local: [
    { name: "qwen2.5-coder:14b", installed: true, default: true },
    { name: "qwen3-coder:30b", installed: false, default: false },
  ],
  gateway: [
    ALLOWED_MODEL,
    { alias: "other-model", provider: "provider-b", allowed: false, reason: "mode", verified_on: "", source: "s" },
  ],
  gateway_enabled: true,
};
const OLD_ID = "11111111-1111-1111-1111-111111111111";
const NEW_ID = "22222222-2222-2222-2222-222222222222";

function baseRoutes(...others: Route[]): Route[] {
  return [
    ...others,
    on("GET", "/v1/me", () => json(ME)),
    on("GET", "/v1/facets", () => json(FACETS)),
    on("GET", "/v1/conversations", () => json([{ id: OLD_ID, title: "Older one", created_at: "2026-11-12T10:00:00Z" }])),
    on("GET", "/v1/models", () => json(MODELS)),
  ];
}

/** Replaces the global fetch (used by the chat stream) for the duration of ``run``. */
async function withFetch(f: typeof fetch, run: () => Promise<void>) {
  const original = globalThis.fetch;
  globalThis.fetch = f;
  try {
    await run();
  } finally {
    globalThis.fetch = original;
  }
}

describe("Boot and sign-in", () => {
  it("token mode: asks for the API token, keeps it in memory and sends it", async () => {
    const { f, requests } = fakeFetch(
      on("GET", "/v1/public-config", () => json({ auth_mode: "token", language: "en", oidc: null })),
      ...baseRoutes(),
    );
    render(<Boot base="http://api.test" fetchFn={f} />);
    const input = await screen.findByLabelText("API token");
    expect(input).toHaveAttribute("type", "password");
    expect(screen.getByText(/~\/\.config\/code-atlas\/api-token/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeDisabled();
    await userEvent.type(input, "my-local-token");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("dev@example.org")).toBeInTheDocument();
    const me = requests.find((r) => r.url.endsWith("/v1/me"));
    expect(me?.headers.get("Authorization")).toBe("Bearer my-local-token");
    expect(requests.find((r) => r.url.endsWith("/v1/public-config"))?.headers.get("Authorization")).toBeNull();
    expect(browserStorageSize()).toBe(0);
  });

  it("token mode: a rejected token is forgotten and the screen says why", async () => {
    const { f } = fakeFetch(
      on("GET", "/v1/public-config", () => json({ auth_mode: "token", language: "en", oidc: null })),
      on("GET", "/v1/me", () => json({ detail: "invalid token" }, 401)),
    );
    render(<Boot base="http://api.test" fetchFn={f} />);
    await userEvent.type(await screen.findByLabelText("API token"), "wrong{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid token");
    expect(screen.getByLabelText("API token")).toHaveValue("");
  });

  it("oidc mode: signs in through the session, then shows the user", async () => {
    const session = fakeSession(false, "oidc");
    const { f } = fakeFetch(
      on("GET", "/v1/public-config", () =>
        json({ auth_mode: "oidc", language: "en", oidc: { issuer: "https://sso.example.org", web_client: "w", desktop_client: "d" } }),
      ),
      ...baseRoutes(),
    );
    const makeSession = vi.fn(() => session);
    render(<Boot base="http://api.test" fetchFn={f} makeSession={makeSession} />);
    expect(screen.queryByLabelText("API token")).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(session.signIn).toHaveBeenCalled();
    expect(makeSession).toHaveBeenCalledWith(expect.objectContaining({ auth_mode: "oidc" }));
    expect(await screen.findByText("dev@example.org")).toBeInTheDocument();
    expect(await screen.findByText("Older one")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(session.signOut).toHaveBeenCalled();
  });

  it("applies the language of the public config", async () => {
    const { f } = fakeFetch(on("GET", "/v1/public-config", () => json({ auth_mode: "token", language: "fr", oidc: null })));
    render(<Boot base="http://api.test" fetchFn={f} />);
    expect(await screen.findByLabelText("Jeton d'API")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("fr");
  });

  it("says when the API cannot be reached", async () => {
    const f = vi.fn(() => Promise.reject(new TypeError("network"))) as unknown as typeof fetch;
    render(<Boot base="http://api.test" fetchFn={f} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("http://api.test");
  });

  it("says when sign-in is cancelled", async () => {
    const session = fakeSession(false);
    session.signIn.mockRejectedValueOnce(new Error("popup closed"));
    const { api } = testApi(session, ...baseRoutes());
    render(<App session={session} api={api} />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in cancelled or refused.");
  });

  it("says why access is refused", async () => {
    const session = fakeSession(true);
    const { api } = testApi(session, on("GET", "/v1/me", () => json({ detail: "access refused" }, 403)));
    render(<App session={session} api={api} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("access refused");
  });
});

describe("App", () => {
  it("searches, shows the chunks then the source", async () => {
    const session = fakeSession();
    const { api, requests } = testApi(
      session,
      ...baseRoutes(on("POST", "/v1/search", () => json({ results: [chunk(1), chunk(2)], duration_ms: 42 }))),
    );
    render(<App session={session} api={api} />);
    await userEvent.click(await screen.findByRole("button", { name: "Search" }));
    await userEvent.type(screen.getByLabelText("What you are looking for"), "may_export");
    await userEvent.click(screen.getByLabelText("python"));
    await userEvent.selectOptions(screen.getByLabelText("How to search"), "lexical");
    await userEvent.click(screen.getByRole("button", { name: "Find" }));
    expect(await screen.findByText("2 results in 42 ms")).toBeInTheDocument();
    const search = requests.find((r) => r.url.endsWith("/v1/search"));
    expect(await search?.json()).toMatchObject({
      question: "may_export",
      filters: { languages: ["python"] },
      mode: "lexical",
      k: 10,
    });
    await userEvent.click(screen.getByText(/app\/f2\.py/));
    const source = screen.getByRole("region", { name: "Source" });
    expect(within(source).getByRole("heading", { name: "function_2" })).toBeInTheDocument();
    await userEvent.click(within(source).getByRole("button", { name: "Close source" }));
    expect(screen.queryByRole("region", { name: "Source" })).not.toBeInTheDocument();
  });

  it("shows an empty search and a search error", async () => {
    const session = fakeSession();
    let calls = 0;
    const { api } = testApi(
      session,
      ...baseRoutes(
        on("POST", "/v1/search", () => (++calls === 1 ? json({ results: [], duration_ms: 3 }) : json({ detail: "x" }, 429))),
      ),
    );
    render(<App session={session} api={api} />);
    await userEvent.click(await screen.findByRole("button", { name: "Search" }));
    await userEvent.type(screen.getByLabelText("What you are looking for"), "nothing{Enter}");
    expect(await screen.findByText(/Nothing found/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Find" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("x");
  });

  it("asks a question, streams the answer and makes citations clickable", async () => {
    const session = fakeSession();
    const { api } = testApi(session, ...baseRoutes());
    const { f, requests } = fakeFetch(() =>
      sseStream([
        [
          "chunks",
          { conversation_id: NEW_ID, model: "qwen2.5-coder:14b", provider: "local", remote: false, chunks: [chunk(1)] },
        ],
        ["token", { text: "Only the owner [1]" }],
        ["token", { text: ", and [5]." }],
        ["done", { conversation_id: NEW_ID, citations: [], invalid_citations: [5] }],
      ]),
    );
    await withFetch(f, async () => {
      render(<App session={session} api={api} />);
      await userEvent.type(await screen.findByLabelText("Your question"), "who may export?{Enter}");
      expect(await screen.findByText(/Only the owner/)).toBeInTheDocument();
      expect(await screen.findByText(/Citations without a matching chunk: \[5\]/)).toBeInTheDocument();
      expect(screen.getByText("qwen2.5-coder:14b · on this machine")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "[1]" }));
      const source = screen.getByRole("region", { name: "Source" });
      expect(within(source).getByRole("heading", { name: "function_1" })).toBeInTheDocument();
      expect(await requests[0]?.json()).toMatchObject({
        question: "who may export?",
        conversation_id: null,
        mode: "local",
        model: "qwen2.5-coder:14b",
        filters: NO_FILTERS,
      });
      expect(requests[0]?.headers.get("Authorization")).toBe("Bearer test-token");
    });
  });

  it("shows a stream error event", async () => {
    const session = fakeSession();
    const { api } = testApi(session, ...baseRoutes());
    const { f } = fakeFetch(() =>
      sseStream([
        ["chunks", { conversation_id: NEW_ID, model: "m", provider: "p", remote: true, chunks: [] }],
        ["error", { reason: "gateway refused the model" }],
      ]),
    );
    await withFetch(f, async () => {
      render(<App session={session} api={api} />);
      await userEvent.type(await screen.findByLabelText("Your question"), "x{Enter}");
      expect(await screen.findByRole("alert")).toHaveTextContent("gateway refused the model");
      expect(screen.getByText("m · ZDR gateway")).toBeInTheDocument();
    });
  });

  it("shows the error of a gateway refusal (409)", async () => {
    const session = fakeSession();
    const { api } = testApi(session, ...baseRoutes());
    const { f } = fakeFetch(() => json({ detail: "refused: alias not on the ZDR list" }, 409));
    await withFetch(f, async () => {
      render(<App session={session} api={api} />);
      await userEvent.type(await screen.findByLabelText("Your question"), "x{Enter}");
      expect(await screen.findByRole("alert")).toHaveTextContent("alias not on the ZDR list");
    });
  });

  it("forgets the session when the chat answers 401", async () => {
    const session = fakeSession();
    const { api } = testApi(session, ...baseRoutes());
    const { f } = fakeFetch(() => json({ detail: "expired" }, 401));
    await withFetch(f, async () => {
      render(<App session={session} api={api} />);
      await userEvent.type(await screen.findByLabelText("Your question"), "x{Enter}");
      await waitFor(() => {
        expect(session.forget).toHaveBeenCalled();
      });
    });
  });

  it("reopens an older conversation", async () => {
    const session = fakeSession();
    const { api } = testApi(
      session,
      ...baseRoutes(
        on("GET", `/v1/conversations/${OLD_ID}`, () =>
          json({
            id: OLD_ID,
            title: "Older one",
            created_at: "2026-11-12T10:00:00Z",
            messages: [
              { role: "user", content: "Older question", model: null, citations: [], created_at: "x" },
              { role: "assistant", content: "Older answer", model: "qwen2.5-coder:14b", citations: [], created_at: "x" },
              { role: "user", content: "Unanswered question", model: null, citations: [], created_at: "x" },
            ],
          }),
        ),
      ),
    );
    render(<App session={session} api={api} />);
    await userEvent.click(await screen.findByRole("button", { name: "Repositories" }));
    await userEvent.click(await screen.findByText("Older one"));
    expect(await screen.findByText("Older answer")).toBeInTheDocument();
    expect(screen.getByText("Unanswered question")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    await waitFor(() => {
      expect(screen.queryByText("Older answer")).not.toBeInTheDocument();
    });
  });
});

describe("ModelPicker", () => {
  it("only lists allowed gateway models and warns when extracts leave", async () => {
    const change = vi.fn();
    const { rerender } = render(
      <ModelPicker models={MODELS} choice={{ mode: "local", model: "qwen2.5-coder:14b" }} change={change} />,
    );
    expect(screen.queryByRole("option", { name: /other-model/ })).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: "qwen3-coder:30b (not installed)" })).toBeDisabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Model"), "gateway|zdr-coder-30b");
    expect(change).toHaveBeenCalledWith({ mode: "gateway", model: "zdr-coder-30b" });
    rerender(<ModelPicker models={MODELS} choice={{ mode: "gateway", model: "zdr-coder-30b" }} change={change} />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Code extracts are sent to provider-a (zero retention, checked on 2026-11-12).",
    );
  });

  it("adds the warning of the gateway model", () => {
    const models = { ...MODELS, gateway: [{ ...ALLOWED_MODEL, warning: "Prompts are logged for 24 h." }] };
    render(<ModelPicker models={models} choice={{ mode: "gateway", model: "zdr-coder-30b" }} change={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Prompts are logged for 24 h.");
  });

  it("hides the gateway when it is not enabled", () => {
    render(
      <ModelPicker
        models={{ ...MODELS, gateway_enabled: false }}
        choice={{ mode: "local", model: "qwen2.5-coder:14b" }}
        change={vi.fn()}
      />,
    );
    expect(screen.queryByRole("option", { name: /zdr-coder/ })).not.toBeInTheDocument();
  });
});

describe("FiltersPanel", () => {
  it("checks, unchecks and clears", async () => {
    const change = vi.fn();
    const { rerender } = render(<FiltersPanel facets={FACETS} filters={NO_FILTERS} change={change} />);
    expect(screen.getByText("Owner")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("doc"));
    expect(change).toHaveBeenLastCalledWith({ ...NO_FILTERS, types: ["doc"] });
    rerender(<FiltersPanel facets={FACETS} filters={{ ...NO_FILTERS, types: ["doc"], owners: ["acme"] }} change={change} />);
    expect(screen.getByText("2")).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("doc"));
    expect(change).toHaveBeenLastCalledWith({ ...NO_FILTERS, owners: ["acme"] });
    await userEvent.click(screen.getByRole("button", { name: "clear" }));
    expect(change).toHaveBeenLastCalledWith(NO_FILTERS);
  });
});

describe("SourcePanel", () => {
  it("shows the chunk then the whole file, without interpreting HTML", async () => {
    const { api, requests } = testApi(
      fakeSession(),
      on("GET", "/v1/files", () =>
        json({
          repo: "acme/api",
          path: "a.py",
          language: "python",
          content: "<img src=x onerror=alert(1)>\nx = 1",
          masked_lines: [],
          url: null,
        }),
      ),
    );
    const { container } = render(<SourcePanel api={api} chunk={chunk(3)} close={vi.fn()} />);
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("rel", "noopener noreferrer");
    await userEvent.click(screen.getByRole("button", { name: "View whole file" }));
    expect(await screen.findByText(/onerror/)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    const url = new URL(requests[0]?.url ?? "");
    expect(url.searchParams.get("repo")).toBe("acme/api");
    expect(url.searchParams.get("path")).toBe("app/f3.py");
  });

  it("hides the link when the chunk has no URL, and the whole file for a notebook cell", () => {
    render(<SourcePanel api={testApi(fakeSession()).api} chunk={chunk(5, { url: null, kind: "cell" })} close={vi.fn()} />);
    expect(screen.queryByRole("link", { name: "Open source" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View whole file" })).not.toBeInTheDocument();
    expect(screen.getByText(/cells 10–12/)).toBeInTheDocument();
  });

  it("invites to pick a chunk", () => {
    render(<SourcePanel api={testApi(fakeSession()).api} chunk={null} close={vi.fn()} />);
    expect(screen.getByText(/Click a result or a citation/)).toBeInTheDocument();
  });

  it("says when the file is unavailable", async () => {
    const { api } = testApi(fakeSession(), on("GET", "/v1/files", () => json({ detail: "x" }, 404)));
    render(<SourcePanel api={api} chunk={chunk(4, { symbol: null, language: "unknown-lang" })} close={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "f4.py" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "View whole file" }));
    expect(await screen.findByText("File unavailable (404)")).toBeInTheDocument();
  });
});

describe("Repos", () => {
  it("lists the repositories and restarts the index after an admin re-login", async () => {
    const session = fakeSession();
    let attempts = 0;
    const { api } = testApi(
      session,
      on("GET", "/v1/repos", () =>
        json([
          { key: "acme/api", commit: "abcdef123", files: 10, chunks: 120, indexed_at: "2026-11-12T10:00:00Z", local_only: true },
        ]),
      ),
      on("GET", "/v1/index", () => json({ running: false, message: null })),
      on("POST", "/v1/index", () =>
        ++attempts === 1 ? json({ detail: "access refused" }, 403) : json({ running: true, message: "choosing the corpus…" }, 202),
      ),
    );
    render(<Repos api={api} session={session} admin />);
    expect(await screen.findByText("1 repository · 120 chunks")).toBeInTheDocument();
    expect(screen.getByText("Last update: none since start-up")).toBeInTheDocument();
    expect(screen.getByText("local")).toHaveAttribute("title", "never leaves this machine");
    expect(screen.getByText("abcdef1")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Update the index" }));
    expect(session.reauthenticate).toHaveBeenCalled();
    expect(await screen.findByText(/Update in progress: choosing the corpus/)).toBeInTheDocument();
  });

  it("shows the error of a refused update", async () => {
    const session = fakeSession(true, "token");
    const { api } = testApi(
      session,
      on("GET", "/v1/repos", () => json([])),
      on("GET", "/v1/index", () => json({ running: false })),
      on("POST", "/v1/index", () => json({ detail: "admin only" }, 403)),
    );
    render(<Repos api={api} session={session} admin />);
    await userEvent.click(await screen.findByRole("button", { name: "Update the index" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("admin only");
  });

  it("hides the button from non-admins", async () => {
    const session = fakeSession();
    const { api } = testApi(session, on("GET", "/v1/repos", () => json([])), on("GET", "/v1/index", () => json({ running: false })));
    render(<Repos api={api} session={session} admin={false} />);
    expect(await screen.findByText("0 repositories · 0 chunks")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Update the index" })).not.toBeInTheDocument();
  });
});

describe("i18n on screen", () => {
  it("switching the language changes the visible text", async () => {
    const session = fakeSession();
    const { api } = testApi(session, ...baseRoutes());
    render(<App session={session} api={api} />);
    expect(await screen.findByRole("button", { name: "New conversation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask" })).toBeInTheDocument();
    act(() => {
      setLanguage("fr");
    });
    expect(screen.getByRole("button", { name: "Nouvelle conversation" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Demander" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dépôts" })).toBeInTheDocument();
    expect(screen.getByLabelText("Ta question")).toBeInTheDocument();
    expect(screen.queryByText("New conversation")).not.toBeInTheDocument();
  });
});
