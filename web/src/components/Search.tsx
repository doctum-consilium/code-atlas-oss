import { useState, type SyntheticEvent } from "react";

import { reason, type Api, type Chunk, type Filters } from "../api/client";
import { t, tn } from "../i18n";
import { useLanguage } from "../useLanguage";
import { ChunkList } from "./ChunkList";

type Mode = "hybrid" | "lexical" | "vector";

export function Search({ api, filters, choose }: { api: Api; filters: Filters; choose: (c: Chunk) => void }) {
  useLanguage();
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<Mode>("hybrid");
  const [results, setResults] = useState<Chunk[] | null>(null);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function search(e: SyntheticEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setRunning(true);
    setError(null);
    const { data, error: failure, response } = await api.POST("/v1/search", {
      body: { question, filters, k: 10, mode },
    });
    setRunning(false);
    if (!data) {
      setError(reason(failure, response.status));
      return;
    }
    setResults(data.results);
    setDuration(data.duration_ms);
  }

  return (
    <section aria-label={t("search.label")}>
      <form className="composer" onSubmit={(e) => void search(e)}>
        <input
          aria-label={t("search.input")}
          placeholder={t("search.placeholder")}
          value={question}
          maxLength={4000}
          onChange={(e) => {
            setQuestion(e.target.value);
          }}
        />
        <select
          aria-label={t("search.mode")}
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as Mode);
          }}
        >
          <option value="hybrid">{t("search.hybrid")}</option>
          <option value="lexical">{t("search.lexical")}</option>
          <option value="vector">{t("search.vector")}</option>
        </select>
        <button type="submit" className="primary" disabled={running}>
          {running ? t("search.running") : t("search.submit")}
        </button>
      </form>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {results && (
        <>
          <p className="muted">{tn("search.count", results.length, { ms: duration })}</p>
          {results.length === 0 ? <p>{t("search.none")}</p> : <ChunkList chunks={results} choose={choose} />}
        </>
      )}
    </section>
  );
}
