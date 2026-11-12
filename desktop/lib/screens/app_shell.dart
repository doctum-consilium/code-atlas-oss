import 'dart:async';

import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../i18n.dart';
import 'chat.dart';
import 'common.dart';
import 'filters.dart';
import 'repos.dart';
import 'search.dart';
import 'source.dart';

/// The signed-in application: history and filters on the left, a screen in the middle, the
/// source on the right.
class AppShell extends StatefulWidget {
  const AppShell({super.key, required this.api});
  final Api api;
  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int _tab = 0;
  Me? _me;
  Facets? _facets;
  Filters _filters = const Filters();
  Chunk? _selected;
  List<ConversationSummary> _history = const [];
  final _chat = GlobalKey<ChatScreenState>();
  Object? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    try {
      final me = await widget.api.me();
      final facets = await widget.api.facets();
      final history = await widget.api.conversations();
      if (!mounted) return;
      setState(() {
        _me = me;
        _facets = facets;
        _history = history;
      });
    } on Exception catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _refreshHistory() async {
    final h = await widget.api.conversations();
    if (mounted) setState(() => _history = h);
  }

  void _select(Chunk c) => setState(() => _selected = c);

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    final me = _me;
    if (me == null) {
      return Scaffold(
        body: Center(
            child: _error == null
                ? const CircularProgressIndicator()
                : Text(describeError(_error!, s))),
      );
    }
    final screens = [
      ChatScreen(
          key: _chat,
          api: widget.api,
          filters: _filters,
          select: _select,
          onNewConversation: _refreshHistory),
      SearchScreen(api: widget.api, filters: _filters, select: _select),
      ReposScreen(api: widget.api, admin: me.admin),
    ];
    final facets = _facets;
    return Scaffold(
      appBar: AppBar(
        title: const Text('code-atlas'),
        actions: [
          SegmentedButton<int>(
            segments: [
              ButtonSegment(value: 0, label: Text(s.t('tab.chat')), icon: const Icon(Icons.forum_outlined)),
              ButtonSegment(value: 1, label: Text(s.t('tab.search')), icon: const Icon(Icons.search)),
              ButtonSegment(
                  value: 2, label: Text(s.t('tab.repos')), icon: const Icon(Icons.inventory_2_outlined)),
            ],
            selected: {_tab},
            onSelectionChanged: (v) => setState(() => _tab = v.first),
          ),
          const SizedBox(width: 16),
          Center(child: Text(me.email, style: Theme.of(context).textTheme.bodySmall)),
          IconButton(
            tooltip: s.t('action.signOut'),
            icon: const Icon(Icons.logout),
            onPressed: widget.api.session.forget,
          ),
        ],
      ),
      body: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SizedBox(
          width: 250,
          child: ListView(padding: const EdgeInsets.all(8), children: [
            FilledButton.tonal(
              onPressed: () {
                setState(() => _tab = 0);
                _chat.currentState?.startNew();
              },
              child: Text(s.t('history.new')),
            ),
            for (final c in _history)
              ListTile(
                dense: true,
                title: Text(c.title, maxLines: 1, overflow: TextOverflow.ellipsis),
                onTap: () {
                  setState(() => _tab = 0);
                  unawaited(_chat.currentState?.open(c.id));
                },
              ),
            const Divider(),
            if (facets != null)
              FiltersPanel(
                facets: facets,
                filters: _filters,
                onChanged: (f) => setState(() => _filters = f),
              ),
          ]),
        ),
        const VerticalDivider(width: 1),
        Expanded(child: IndexedStack(index: _tab, children: screens)),
        const VerticalDivider(width: 1),
        SizedBox(
          width: 520,
          child: SourcePanel(
            key: ValueKey(_selected?.id),
            api: widget.api,
            chunk: _selected,
            onClose: () => setState(() => _selected = null),
          ),
        ),
      ]),
    );
  }
}
