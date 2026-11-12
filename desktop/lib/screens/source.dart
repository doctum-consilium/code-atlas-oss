import 'package:flutter/material.dart';
import 'package:re_highlight/languages/all.dart';
import 'package:re_highlight/re_highlight.dart';
import 'package:re_highlight/styles/github-dark.dart';
import 'package:re_highlight/styles/github.dart';
import 'package:url_launcher/url_launcher_string.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../i18n.dart';
import 'common.dart';

final Highlight _highlighter = Highlight()..registerLanguages(builtinAllLanguages);

const _aliases = {'tsx': 'typescript', 'bash': 'bash', 'latex': 'latex', 'csharp': 'csharp'};

/// Highlighted code as a [TextSpan] (no HTML is interpreted: the code stays text).
TextSpan highlight(String code, String language, Map<String, TextStyle> style, TextStyle base) {
  final name = _aliases[language] ?? language;
  final result = builtinAllLanguages.containsKey(name)
      ? _highlighter.highlight(code: code, language: name)
      : _highlighter.justTextHighlightResult(code);
  final renderer = TextSpanRenderer(base, style);
  result.render(renderer);
  return renderer.span ?? TextSpan(text: code, style: base);
}

/// Highlighted code with line numbers starting at [firstLine].
class HighlightedCode extends StatelessWidget {
  const HighlightedCode({super.key, required this.code, required this.language, required this.firstLine});
  final String code;
  final String language;
  final int firstLine;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    const base = TextStyle(fontFamily: 'monospace', fontSize: 12.5, height: 1.4);
    final lines = '\n'.allMatches(code).length + 1;
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(
          List.generate(lines, (i) => '${firstLine + i}').join('\n'),
          key: const Key('line-numbers'),
          textAlign: TextAlign.right,
          style: base.copyWith(color: Theme.of(context).disabledColor),
        ),
        const SizedBox(width: 12),
        SelectableText.rich(highlight(code, language, dark ? githubDarkTheme : githubTheme, base)),
      ]),
    );
  }
}

class SourcePanel extends StatefulWidget {
  const SourcePanel({super.key, required this.api, required this.chunk, required this.onClose});
  final Api api;
  final Chunk? chunk;
  final VoidCallback onClose;
  @override
  State<SourcePanel> createState() => _SourcePanelState();
}

class _SourcePanelState extends State<SourcePanel> {
  FileContent? _file;
  int? _failedStatus;

  Future<void> _wholeFile(Chunk c) async {
    try {
      final f = await widget.api.file(c.repo, c.path);
      if (mounted) setState(() => _file = f);
    } on ApiException catch (e) {
      if (mounted) setState(() => _failedStatus = e.status);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    final c = widget.chunk;
    if (c == null) return Center(child: Text(s.t('source.empty')));
    final theme = Theme.of(context);
    final file = _file;
    final url = c.url;
    return ListView(padding: const EdgeInsets.all(12), children: [
      Row(children: [
        Expanded(
          child: Text(c.symbol ?? c.path.split('/').last,
              style: theme.textTheme.titleMedium?.copyWith(fontFamily: 'monospace')),
        ),
        IconButton(tooltip: s.t('source.close'), icon: const Icon(Icons.close), onPressed: widget.onClose),
      ]),
      Text(chunkLabel(c, s), style: theme.textTheme.bodySmall),
      Wrap(spacing: 8, children: [
        if (url != null)
          TextButton.icon(
            icon: const Icon(Icons.open_in_new, size: 16),
            label: Text(s.t('source.open')),
            onPressed: () => launchUrlString(url),
          ),
        if (!c.isCell && file == null)
          TextButton(onPressed: () => _wholeFile(c), child: Text(s.t('source.wholeFile'))),
      ]),
      if (_failedStatus != null)
        Text(s.t('source.unavailable', {'status': _failedStatus}),
            style: TextStyle(color: theme.colorScheme.error)),
      if (file != null && file.maskedLines.isNotEmpty)
        Text(s.t('source.masked', {'lines': file.maskedLines.join(', ')}),
            style: TextStyle(color: Colors.orange.shade800)),
      const SizedBox(height: 8),
      file == null
          ? HighlightedCode(code: c.text, language: c.language, firstLine: c.lineStart)
          : HighlightedCode(code: file.content, language: file.language, firstLine: 1),
    ]);
  }
}
