import { useEffect, useRef, useState, type SyntheticEvent } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Api, Chunk, Citation, Filters, Models } from "../api/client";
import { ApiError, ask } from "../api/stream";
import type { Session } from "../auth";
import { citationNumber, linkCitations } from "../citations";
import { config } from "../config";
import { t } from "../i18n";
import { useLanguage } from "../useLanguage";
import { ChunkList } from "./ChunkList";
import { ModelPicker, type Choice } from "./ModelPicker";

export type Exchange = {
  question: string;
  answer: string;
  chunks: Chunk[];
  citations: Citation[];
  invalid: number[];
  model: string;
  remote: boolean;
  state: "running" | "done" | "error";
  error?: string;
};

export function Chat({
  api,
  session,
  filters,
  conversationId,
  exchanges,
  setExchanges,
  choose,
  onNewConversation,
}: {
  api: Api;
  session: Session;
  filters: Filters;
  conversationId: string | null;
  exchanges: Exchange[];
  setExchanges: (f: (e: Exchange[]) => Exchange[]) => void;
  choose: (c: Chunk) => void;
  onNewConversation: (id: string) => void;
}) {
  useLanguage();
  const [question, setQuestion] = useState("");
  const [models, setModels] = useState<Models | null>(null);
  const [choice, setChoice] = useState<Choice | null>(null);
  const stop = useRef<AbortController | null>(null);

  useEffect(() => {
    void (async () => {
      const { data } = await api.GET("/v1/models");
      if (!data) return;
      setModels(data);
      const fallback = data.local.find((m) => m.default) ?? data.local[0];
      if (fallback) setChoice({ mode: "local", model: fallback.name });
    })();
  }, [api]);

  function update(index: number, f: (e: Exchange) => Exchange) {
    setExchanges((all) => all.map((e, i) => (i === index ? f(e) : e)));
  }

  async function send(e: SyntheticEvent) {
    e.preventDefault();
    const text = question.trim();
    if (!text || !choice) return;
    setQuestion("");
    const index = exchanges.length;
    setExchanges((all) => [
      ...all,
      {
        question: text,
        answer: "",
        chunks: [],
        citations: [],
        invalid: [],
        model: choice.model,
        remote: choice.mode === "gateway",
        state: "running",
      },
    ]);
    stop.current = new AbortController();
    try {
      const events = ask(
        config.api,
        session.token(),
        { question: text, conversation_id: conversationId, mode: choice.mode, model: choice.model, filters },
        stop.current.signal,
      );
      for await (const ev of events) {
        if (ev.type === "chunks") {
          update(index, (x) => ({ ...x, chunks: ev.chunks, remote: ev.remote, model: ev.model }));
          if (!conversationId) onNewConversation(ev.conversation_id);
        } else if (ev.type === "token") {
          update(index, (x) => ({ ...x, answer: x.answer + ev.text }));
        } else if (ev.type === "done") {
          update(index, (x) => ({ ...x, citations: ev.citations, invalid: ev.invalid_citations, state: "done" }));
        } else {
          update(index, (x) => ({ ...x, state: "error", error: ev.reason }));
        }
      }
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) session.forget();
      const message = failure instanceof Error ? failure.message : t("chat.unknownError");
      update(index, (x) => ({ ...x, state: "error", error: message }));
    }
  }

  const running = exchanges.some((e) => e.state === "running");

  return (
    <section aria-label={t("chat.label")} className="chat">
      <div className="thread">
        {exchanges.length === 0 && <p className="muted">{t("chat.intro")}</p>}
        {exchanges.map((e, i) => (
          <article key={i} className="exchange">
            <p className="question">{e.question}</p>
            <div className={e.remote ? "answer remote" : "answer"}>
              <p className="muted">{t(e.remote ? "chat.gateway" : "chat.local", { model: e.model })}</p>
              <Markdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ href, children }) => {
                    const n = citationNumber(href);
                    const chunk = n ? e.chunks[n - 1] : undefined;
                    if (n && chunk) {
                      return (
                        <button
                          type="button"
                          className="citation"
                          title={`${chunk.repo}/${chunk.path}`}
                          onClick={() => {
                            choose(chunk);
                          }}
                        >
                          {children}
                        </button>
                      );
                    }
                    return <span>{children}</span>;
                  },
                }}
              >
                {linkCitations(e.answer, e.chunks.length)}
              </Markdown>
              {e.state === "running" && <p className="muted">…</p>}
              {e.state === "error" && (
                <p role="alert" className="error">
                  {e.error}
                </p>
              )}
              {e.invalid.length > 0 && (
                <p className="warning">{t("chat.invalid", { list: e.invalid.map((n) => `[${n}]`).join(" ") })}</p>
              )}
              {e.chunks.length > 0 && (
                <details>
                  <summary>{t("chat.sources", { n: e.chunks.length })}</summary>
                  <ChunkList chunks={e.chunks} choose={choose} numbered />
                </details>
              )}
            </div>
          </article>
        ))}
      </div>
      <form className="composer" onSubmit={(ev) => void send(ev)}>
        <textarea
          aria-label={t("chat.input")}
          placeholder={t("chat.placeholder")}
          value={question}
          maxLength={4000}
          rows={2}
          onChange={(ev) => {
            setQuestion(ev.target.value);
          }}
          onKeyDown={(ev) => {
            if (ev.key === "Enter" && !ev.shiftKey) {
              ev.preventDefault();
              ev.currentTarget.form?.requestSubmit();
            }
          }}
        />
        {models && choice && <ModelPicker models={models} choice={choice} change={setChoice} />}
        {running ? (
          <button type="button" onClick={() => stop.current?.abort()}>
            {t("chat.stop")}
          </button>
        ) : (
          <button type="submit" className="primary" disabled={!choice}>
            {t("chat.ask")}
          </button>
        )}
      </form>
    </section>
  );
}
