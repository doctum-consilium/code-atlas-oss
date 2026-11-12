import 'dart:async';

import 'package:flutter/material.dart';

import '../api/client.dart';
import '../api/models.dart';
import '../i18n.dart';
import 'common.dart';

class ReposScreen extends StatefulWidget {
  const ReposScreen({super.key, required this.api, required this.admin});
  final Api api;
  final bool admin;
  @override
  State<ReposScreen> createState() => _ReposScreenState();
}

class _ReposScreenState extends State<ReposScreen> {
  List<Repo>? _repos;
  IndexStatus? _status;
  Object? _error;
  Timer? _poll;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final repos = await widget.api.repos();
      final status = await widget.api.indexStatus();
      if (!mounted) return;
      setState(() {
        _repos = repos;
        _status = status;
      });
      _poll?.cancel();
      if (status.running) _poll = Timer(const Duration(seconds: 5), () => unawaited(_load()));
    } on Exception catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  Future<void> _reindex() async {
    setState(() => _error = null);
    final session = widget.api.session;
    try {
      try {
        _status = await widget.api.startIndex();
      } on ApiException catch (e) {
        if (e.status != 403 || !session.canReauthenticate) rethrow;
        // Admin action: the identity provider must have seen a recent login. Sign in again
        // (prompt=login), then retry once.
        await session.login(forceLogin: true);
        _status = await widget.api.startIndex();
      }
    } on Exception catch (e) {
      _error = e;
    }
    if (mounted) setState(() {});
    unawaited(_load());
  }

  @override
  Widget build(BuildContext context) {
    final s = I18n.of(context);
    final repos = _repos;
    final status = _status;
    final total = repos?.fold<int>(0, (n, r) => n + r.chunks) ?? 0;
    return ListView(padding: const EdgeInsets.all(16), children: [
      Text(
          repos == null
              ? s.t('repos.loading')
              : s.t('repos.summary', {'repos': repos.length, 'chunks': total}),
          style: Theme.of(context).textTheme.titleMedium),
      if (status != null)
        Text(s.t(status.running ? 'repos.running' : 'repos.last',
            {'message': status.message ?? s.t('repos.none')})),
      if (widget.admin)
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton(
            key: const Key('reindex'),
            onPressed: status?.running ?? false ? null : _reindex,
            child: Text(s.t('repos.reindex')),
          ),
        ),
      if (_error != null)
        Text(describeError(_error!, s), style: TextStyle(color: Theme.of(context).colorScheme.error)),
      if (repos != null)
        DataTable(columns: [
          DataColumn(label: Text(s.t('repos.col.repo'))),
          DataColumn(label: Text(s.t('repos.col.files')), numeric: true),
          DataColumn(label: Text(s.t('repos.col.chunks')), numeric: true),
          DataColumn(label: Text(s.t('repos.col.commit'))),
        ], rows: [
          for (final r in repos)
            DataRow(cells: [
              DataCell(Text('${r.key}${r.localOnly ? ' · ${s.t('repos.localOnly')}' : ''}')),
              DataCell(Text('${r.files}')),
              DataCell(Text('${r.chunks}')),
              DataCell(Text(r.commit.length > 7 ? r.commit.substring(0, 7) : r.commit)),
            ]),
        ]),
    ]);
  }
}
