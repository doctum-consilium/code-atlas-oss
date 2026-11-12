/**
 * The "[n]" citations of an answer become internal links to chunk n.
 *
 * Only the numbers of chunks actually supplied become clickable; a number invented by the model
 * stays text, and is marked as such.
 */
export const PREFIX = "#chunk-";

export function linkCitations(text: string, chunkCount: number): string {
  // Outside code blocks: a citation has nothing to do in copied code.
  return text
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((piece, i) =>
      i % 2 === 1
        ? piece
        : piece.replace(/\[(\d{1,2})\](?!\()/g, (whole, n: string) => {
            const number = Number(n);
            return number >= 1 && number <= chunkCount ? `[\\[${n}\\]](${PREFIX}${n})` : `${whole}⁇`;
          }),
    )
    .join("");
}

export function citationNumber(href: string | undefined): number | null {
  if (!href?.startsWith(PREFIX)) return null;
  const n = Number(href.slice(PREFIX.length));
  return Number.isInteger(n) ? n : null;
}
