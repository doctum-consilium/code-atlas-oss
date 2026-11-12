import hljs from "highlight.js/lib/common";
import { useMemo, useState } from "react";

import type { Api, Chunk, FileContent } from "../api/client";
import { t } from "../i18n";
import { useLanguage } from "../useLanguage";
import { location } from "./ChunkList";

const ALIASES: Record<string, string> = { tsx: "typescript", dart: "dart", kotlin: "kotlin", latex: "latex" };

/** Highlighted code; highlight.js escapes the text, so no HTML from a repository is interpreted. */
export function HighlightedCode({ code, language, first }: { code: string; language: string; first: number }) {
  const html = useMemo(() => {
    const name = ALIASES[language] ?? language;
    return hljs.getLanguage(name) ? hljs.highlight(code, { language: name }).value : hljs.highlightAuto(code).value;
  }, [code, language]);
  const count = code.split("\n").length;
  return (
    <div className="code">
      <pre className="line-numbers" aria-hidden="true">
        {Array.from({ length: count }, (_v, i) => first + i).join("\n")}
      </pre>
      <pre>
        <code className="hljs" dangerouslySetInnerHTML={{ __html: html }} />
      </pre>
    </div>
  );
}

export function SourcePanel({ api, chunk, close }: { api: Api; chunk: Chunk | null; close: () => void }) {
  useLanguage();
  const [file, setFile] = useState<FileContent | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!chunk) {
    return <p className="muted">{t("source.empty")}</p>;
  }

  async function wholeFile() {
    if (!chunk) return;
    const { data, response } = await api.GET("/v1/files", {
      params: { query: { repo: chunk.repo, path: chunk.path } },
    });
    if (data) setFile(data);
    else setError(t("source.unavailable", { status: response.status }));
  }

  return (
    <section aria-label={t("source.label")} className="source">
      <header>
        <h2>{chunk.symbol ?? chunk.path.split("/").pop()}</h2>
        <button type="button" className="link" onClick={close} aria-label={t("source.close")}>
          ✕
        </button>
      </header>
      <p className="path">{location(chunk)}</p>
      <p>
        {chunk.url && (
          <a href={chunk.url} target="_blank" rel="noopener noreferrer">
            {t("source.open")}
          </a>
        )}
        {chunk.kind !== "cell" && !file && (
          <button type="button" className="link" onClick={() => void wholeFile()}>
            {t("source.wholeFile")}
          </button>
        )}
      </p>
      {error && <p className="error">{error}</p>}
      {file ? (
        <HighlightedCode code={file.content} language={file.language} first={1} />
      ) : (
        <HighlightedCode code={chunk.text} language={chunk.language} first={chunk.line_start} />
      )}
    </section>
  );
}
