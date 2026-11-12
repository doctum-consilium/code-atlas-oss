import type { Chunk } from "../api/client";
import { t } from "../i18n";
import { useLanguage } from "../useLanguage";

export function location(c: Chunk): string {
  return t("chunk.location", {
    repo: c.repo,
    path: c.path,
    unit: t(c.kind === "cell" ? "chunk.cells" : "chunk.lines"),
    start: c.line_start,
    end: c.line_end,
  });
}

export function ChunkList({
  chunks,
  choose,
  numbered = false,
}: {
  chunks: Chunk[];
  choose: (c: Chunk) => void;
  numbered?: boolean;
}) {
  useLanguage();
  return (
    <ol className="chunks">
      {chunks.map((c, i) => (
        <li key={c.id} id={numbered ? `source-${i + 1}` : undefined}>
          <button
            type="button"
            className="chunk"
            onClick={() => {
              choose(c);
            }}
          >
            <span className="path">
              {numbered && <b>[{i + 1}] </b>}
              {location(c)}
            </span>
            {c.symbol && <span className="symbol">{c.symbol}</span>}
            <code className="preview">{c.text.split("\n").slice(0, 3).join("\n")}</code>
          </button>
        </li>
      ))}
    </ol>
  );
}
