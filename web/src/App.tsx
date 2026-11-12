import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

import type { Api, Chunk, Conversation, ConversationSummary, Facets, Filters, Me } from "./api/client";
import { emptyFilters, reason } from "./api/client";
import type { Session } from "./auth";
import { Chat, type Exchange } from "./components/Chat";
import { FiltersPanel } from "./components/FiltersPanel";
import { History } from "./components/History";
import { Repos } from "./components/Repos";
import { Search } from "./components/Search";
import { SignIn } from "./components/SignIn";
import { SourcePanel } from "./components/SourcePanel";
import { t, type Key } from "./i18n";
import { useLanguage } from "./useLanguage";

type Tab = "search" | "ask" | "repos";

const TABS: Record<Tab, Key> = { ask: "nav.ask", search: "nav.search", repos: "nav.repos" };

/** Rebuilds the exchanges of a stored conversation: each user message with the answer after it. */
export function restoreExchanges(conversation: Conversation): Exchange[] {
  const exchanges: Exchange[] = [];
  const { messages } = conversation;
  for (let i = 0; i < messages.length; i++) {
    const message = messages[i];
    if (message?.role !== "user") continue;
    const next = messages[i + 1];
    const answer = next?.role === "assistant" ? next : undefined;
    exchanges.push({
      question: message.content,
      answer: answer?.content ?? "",
      chunks: [],
      citations: answer?.citations ?? [],
      invalid: [],
      model: answer?.model ?? "",
      remote: false,
      state: "done",
    });
  }
  return exchanges;
}

export function App({ session, api }: { session: Session; api: Api }) {
  useLanguage();
  const connected = useSyncExternalStore(
    (callback) => session.subscribe(callback),
    () => session.connected,
  );
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("ask");
  const [facets, setFacets] = useState<Facets | null>(null);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [selection, setSelection] = useState<Chunk | null>(null);
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);

  const refreshHistory = useCallback(async () => {
    const { data } = await api.GET("/v1/conversations");
    if (data) setHistory(data);
  }, [api]);

  useEffect(() => {
    if (!connected) return;
    void (async () => {
      const { data, error: failure, response } = await api.GET("/v1/me");
      if (!data) {
        setError(reason(failure, response.status));
        return;
      }
      setMe(data);
      setError(null);
      const f = await api.GET("/v1/facets");
      if (f.data) setFacets(f.data);
      await refreshHistory();
    })();
  }, [api, connected, refreshHistory]);

  const openConversation = useCallback(
    async (id: string | null) => {
      setSelection(null);
      setConversationId(id);
      if (!id) {
        setExchanges([]);
        return;
      }
      const { data } = await api.GET("/v1/conversations/{conversation_id}", {
        params: { path: { conversation_id: id } },
      });
      if (!data) return;
      setExchanges(restoreExchanges(data));
      setTab("ask");
    },
    [api],
  );

  if (!connected || !me) {
    return (
      <SignIn
        mode={session.mode}
        error={error}
        signIn={(secret) => {
          setError(null);
          session.signIn(secret).catch(() => {
            setError(t("signin.cancelled"));
          });
        }}
      />
    );
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>{t("app.title")}</h1>
        <nav aria-label={t("nav.label")}>
          {(["ask", "search", "repos"] as const).map((name) => (
            <button
              key={name}
              type="button"
              className={tab === name ? "tab active" : "tab"}
              aria-pressed={tab === name}
              onClick={() => {
                setTab(name);
              }}
            >
              {t(TABS[name])}
            </button>
          ))}
        </nav>
        <span className="me">
          {me.email}
          <button type="button" className="link" onClick={() => void session.signOut()}>
            {t("header.signOut")}
          </button>
        </span>
      </header>
      <aside className="left">
        <History conversations={history} current={conversationId} open={(id) => void openConversation(id)} />
        {facets && <FiltersPanel facets={facets} filters={filters} change={setFilters} />}
      </aside>
      <main className="center">
        {tab === "search" && <Search api={api} filters={filters} choose={setSelection} />}
        {tab === "ask" && (
          <Chat
            api={api}
            session={session}
            filters={filters}
            conversationId={conversationId}
            exchanges={exchanges}
            setExchanges={setExchanges}
            choose={setSelection}
            onNewConversation={(id) => {
              setConversationId(id);
              void refreshHistory();
            }}
          />
        )}
        {tab === "repos" && <Repos api={api} session={session} admin={me.admin} />}
      </main>
      <aside className="right">
        <SourcePanel
          key={selection?.id ?? 0}
          api={api}
          chunk={selection}
          close={() => {
            setSelection(null);
          }}
        />
      </aside>
    </div>
  );
}
