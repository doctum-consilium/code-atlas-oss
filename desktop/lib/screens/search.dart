import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../i18n.dart';
import 'chunks.dart';
import 'common.dart';

class SearchScreen extends StatefulWidget {
  const SearchScreen({super.key, required this.api, required this.filters, required this.select});
  final Api api;
  final Filters filters;
  final void Function(Chunk) select;
  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  final _input = TextEditingController();
  String _mode = 'hybrid';
  SearchResult? _result;
  Object? _error;
  bool _running = false;

  @override
  void dispose() {
    _input.dispose();
    super.dispose();
  }

  Future<void> _search() async {
    if (_input.text.trim().isEmpty) return;
    setState(() {
      _running = true;
      _error = null;
    });
    try {
      final r = await widget.api.search(_input.text, widget.filters, mode: _mode);
      if (mounted) setState(() => _result = r);
    } on Exception catch (e) {
      if (mounted) setState(() => _error = e);
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    final result = _result;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Row(children: [
        Expanded(
          child: TextField(
            key: const Key('search'),
            controller: _input,
            maxLength: 4000,
            decoration: InputDecoration(
              hintText: s.t('search.hint'),
              counterText: '',
              border: const OutlineInputBorder(),
            ),
            onSubmitted: (_) => _search(),
          ),
        ),
        const SizedBox(width: 8),
        DropdownButton<String>(
          key: const Key('search-mode'),
          value: _mode,
          items: [
            for (final m in const ['hybrid', 'lexical', 'vector'])
              DropdownMenuItem(value: m, child: Text(s.t('search.$m'))),
          ],
          onChanged: (m) => setState(() => _mode = m ?? 'hybrid'),
        ),
        const SizedBox(width: 8),
        FilledButton(onPressed: _running ? null : _search, child: Text(s.t('search.go'))),
      ]),
      if (_error != null)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(describeError(_error!, s),
              style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ),
      if (result != null) ...[
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(s.t('search.count', {'count': result.results.length, 'ms': result.durationMs})),
        ),
        if (result.results.isEmpty)
          Text(s.t('search.none'))
        else
          ChunkList(chunks: result.results, select: widget.select),
      ],
    ]);
  }
}
