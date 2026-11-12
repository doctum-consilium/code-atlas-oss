/// The "[n]" citations of an answer become internal links to chunk n.
///
/// Only numbers of chunks actually supplied become clickable (the link text keeps its brackets,
/// "[n]"); an invented number stays plain text, followed by "⁇". Code (between backticks) is
/// never touched.
library;

const citationPrefix = 'chunk:';

final _code = RegExp(r'(```[\s\S]*?```|`[^`\n]*`)');

String linkCitations(String text, int chunkCount) {
  final pieces = text.split(_code);
  final codes = _code.allMatches(text).map((m) => m[0]!).toList();
  final out = StringBuffer();
  for (var i = 0; i < pieces.length; i++) {
    out.write(pieces[i].replaceAllMapped(RegExp(r'\[(\d{1,2})\](?!\()'), (m) {
      final n = int.parse(m[1]!);
      return n >= 1 && n <= chunkCount ? '[\\[$n\\]]($citationPrefix$n)' : '${m[0]}⁇';
    }));
    if (i < codes.length) out.write(codes[i]);
  }
  return out.toString();
}

int? citationNumber(String? href) {
  if (href == null || !href.startsWith(citationPrefix)) return null;
  return int.tryParse(href.substring(citationPrefix.length));
}
