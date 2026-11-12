import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import '../api/client.dart';
import '../api/events.dart';
import '../api/models.dart';
import '../citations.dart';
import '../i18n.dart';
import 'chunks.dart';
import 'common.dart';

/// One question and its answer.
class Exchange {
  Exchange(this.question, {this.model = '', this.remote = false});
  final String question;
  String answer = '';
  List<Chunk> chunks = const [];
  List<int> invalidCitations = const [];
  String model;
  bool remote;
  bool done = false;
  Object? error;
}

/// The chosen model: `mode` is `local` or `gateway`.
typedef ModelChoice = ({String mode, String model});

class ChatScreen extends StatefulWidget {
  const ChatScreen({
    super.key,
    required this.api,
    required this.filters,
    required this.select,
    required this.onNewConversation,
  });
  final Api api;
  final Filters filters;
  final void Function(Chunk) select;
  final Future<void> Function() onNewConversation;
  @override
  State<ChatScreen> createState() => ChatScreenState();
}

class ChatScreenState extends State<ChatScreen> {
  final _input = TextEditingController();
  final List<Exchange> _exchanges = [];
  Models? _models;
  ModelChoice? _choice;
  String? _conversationId;
  StreamSubscription<ChatEvent>? _stream;

  @override
  void initState() {
    super.initState();
    unawaited(_loadModels());
  }

  @override
  void dispose() {
    unawaited(_stream?.cancel());
    _input.dispose();
    super.dispose();
  }

  Future<void> _loadModels() async {
    try {
      final m = await widget.api.models();
      final installed = m.local.where((l) => l.installed);
      final preferred = installed.where((l) => l.isDefault).firstOrNull ?? installed.firstOrNull;
      if (!mounted) return;
      setState(() {
        _models = m;
        if (preferred != null) _choice = (mode: 'local', model: preferred.name);
      });
    } on Exception {
      // The screen stays usable without a model list: the Ask button stays disabled.
    }
  }

  void startNew() => setState(() {
        _exchanges.clear();
        _conversationId = null;
      });

  Future<void> open(String conversationId) async {
    final messages = await widget.api.conversation(conversationId);
    if (!mounted) return;
    setState(() {
      _conversationId = conversationId;
      _exchanges.clear();
      for (final m in messages) {
        if (m.role == 'user') {
          _exchanges.add(Exchange(m.content)..done = true);
        } else if (_exchanges.isNotEmpty) {
          _exchanges.last
            ..answer = m.content
            ..model = m.model ?? '';
        }
      }
    });
  }

  void _send() {
    final question = _input.text.trim();
    final choice = _choice;
    if (question.isEmpty || choice == null || _stream != null) return;
    _input.clear();
    final exchange = Exchange(question, model: choice.model, remote: choice.mode == 'gateway');
    setState(() => _exchanges.add(exchange));
    final isNew = _conversationId == null;
    _stream = widget.api
        .ask(
          question: question,
          mode: choice.mode,
          model: choice.model,
          filters: widget.filters,
          conversationId: _conversationId,
        )
        .listen(
          (e) => setState(() => _receive(exchange, e, isNew)),
          onError: (Object e) => setState(() {
            exchange.error = e;
            _stream = null;
          }),
          onDone: () => setState(() => _stream = null),
        );
  }

  void _receive(Exchange exchange, ChatEvent event, bool isNew) {
    switch (event) {
      case ChunksEvent():
        exchange
          ..chunks = event.chunks
          ..model = event.model
          ..remote = event.remote;
        _conversationId = event.conversationId;
        if (isNew) unawaited(widget.onNewConversation());
      case TokenEvent():
        exchange.answer += event.text;
      case DoneEvent():
        exchange
          ..invalidCitations = event.invalidCitations
          ..done = true;
      case ErrorEvent():
        exchange.error = event.reason;
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    final choice = _choice;
    final models = _models;
    final remote = choice?.mode == 'gateway'
        ? models?.offeredGateway.where((m) => m.alias == choice!.model).firstOrNull
        : null;
    return Column(children: [
      Expanded(
        child: ListView(padding: const EdgeInsets.all(16), children: [
          if (_exchanges.isEmpty) Text(s.t('chat.empty')),
          for (final e in _exchanges) _ExchangeView(exchange: e, select: widget.select),
        ]),
      ),
      if (remote != null)
        Container(
          key: const Key('remote-banner'),
          width: double.infinity,
          color: Colors.orange.withValues(alpha: .15),
          padding: const EdgeInsets.all(8),
          child: Text(
            '${s.t('chat.remoteBanner', {'provider': remote.provider, 'date': remote.verifiedOn})}'
            '${remote.warning == null ? '' : ' ${remote.warning}'}',
            style: TextStyle(color: Colors.orange.shade900),
          ),
        ),
      Padding(
        padding: const EdgeInsets.all(12),
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Expanded(
            child: TextField(
              key: const Key('question'),
              controller: _input,
              minLines: 1,
              maxLines: 6,
              maxLength: 4000,
              decoration: InputDecoration(
                hintText: s.t('chat.hint'),
                counterText: '',
                border: const OutlineInputBorder(),
              ),
              onSubmitted: (_) => _send(),
            ),
          ),
          const SizedBox(width: 8),
          if (models != null && choice != null)
            _ModelPicker(models: models, choice: choice, onChanged: (c) => setState(() => _choice = c)),
          const SizedBox(width: 8),
          _stream == null
              ? FilledButton(onPressed: choice == null ? null : _send, child: Text(s.t('chat.ask')))
              : OutlinedButton(
                  onPressed: () {
                    unawaited(_stream?.cancel());
                    setState(() => _stream = null);
                  },
                  child: Text(s.t('chat.stop')),
                ),
        ]),
      ),
    ]);
  }
}

/// Local models, then the gateway models allowed by the policy (and only when the gateway is on).
class _ModelPicker extends StatelessWidget {
  const _ModelPicker({required this.models, required this.choice, required this.onChanged});
  final Models models;
  final ModelChoice choice;
  final void Function(ModelChoice) onChanged;

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    return DropdownButton<String>(
      key: const Key('model'),
      value: '${choice.mode}|${choice.model}',
      items: [
        for (final m in models.local)
          DropdownMenuItem(
            value: 'local|${m.name}',
            enabled: m.installed,
            child: Text(s.t(m.installed ? 'model.local' : 'model.notInstalled', {'name': m.name})),
          ),
        for (final m in models.offeredGateway)
          DropdownMenuItem(
            value: 'gateway|${m.alias}',
            child: Text(s.t('model.gateway', {'alias': m.alias, 'provider': m.provider})),
          ),
      ],
      onChanged: (v) {
        if (v == null) return;
        final split = v.indexOf('|');
        onChanged((mode: v.substring(0, split), model: v.substring(split + 1)));
      },
    );
  }
}

class _ExchangeView extends StatelessWidget {
  const _ExchangeView({required this.exchange, required this.select});
  final Exchange exchange;
  final void Function(Chunk) select;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final s = I18n.of(context);
    final e = exchange;
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Card(child: Padding(padding: const EdgeInsets.all(10), child: SelectableText(e.question))),
        Container(
          decoration: BoxDecoration(
            border: Border(
                left: BorderSide(width: 3, color: e.remote ? Colors.orange : theme.dividerColor)),
          ),
          padding: const EdgeInsets.only(left: 12, top: 6),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('${e.model} · ${s.t(e.remote ? 'chat.gateway' : 'chat.local')}',
                style: theme.textTheme.bodySmall),
            MarkdownBody(
              data: linkCitations(e.answer, e.chunks.length),
              selectable: true,
              onTapLink: (text, href, title) {
                final n = citationNumber(href);
                if (n != null && n >= 1 && n <= e.chunks.length) select(e.chunks[n - 1]);
              },
            ),
            if (!e.done && e.error == null) const LinearProgressIndicator(),
            if (e.error != null)
              Text(describeError(e.error!, s), style: TextStyle(color: theme.colorScheme.error)),
            if (e.invalidCitations.isNotEmpty)
              Text(
                  s.t('chat.invalidCitations',
                      {'list': e.invalidCitations.map((n) => '[$n]').join(' ')}),
                  style: TextStyle(color: Colors.orange.shade800)),
            if (e.chunks.isNotEmpty)
              ExpansionTile(
                title: Text(s.t('chat.sources', {'count': e.chunks.length})),
                tilePadding: EdgeInsets.zero,
                children: [ChunkList(chunks: e.chunks, select: select, numbered: true)],
              ),
          ]),
        ),
      ]),
    );
  }
}
