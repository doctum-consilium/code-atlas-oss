/// Start-up: read the server's public configuration, choose the sign-in mode and the language,
/// then show the sign-in screen or the application.
library;

import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import 'api/client.dart';
import 'api/models.dart';
import 'auth/oidc.dart';
import 'auth/session.dart';
import 'config.dart';
import 'i18n.dart';
import 'screens/app_shell.dart';
import 'screens/common.dart';
import 'screens/sign_in.dart';

/// Builds the token source for the server's `auth_mode` (tests inject fakes).
typedef AuthFactory = AuthSource Function(PublicConfig config, Strings strings);

AuthSource defaultAuth(PublicConfig config, Strings strings) {
  if (config.authMode == 'oidc') {
    final oidc = config.oidc;
    if (oidc == null) throw const FormatException('auth_mode is oidc but no oidc settings');
    return OidcAuth(
        OidcClient(issuer: oidc.issuer, clientId: oidc.desktopClient, strings: strings));
  }
  return TokenFileAuth(tokenFilePath(Platform.environment));
}

class CodeAtlasApp extends StatefulWidget {
  const CodeAtlasApp({
    super.key,
    required this.apiBase,
    required this.httpClient,
    this.authFactory = defaultAuth,
    this.platformLanguage,
  });

  final String apiBase;
  final http.Client httpClient;
  final AuthFactory authFactory;

  /// Overrides the platform locale's language (tests).
  final String? platformLanguage;

  @override
  State<CodeAtlasApp> createState() => _CodeAtlasAppState();
}

class _CodeAtlasAppState extends State<CodeAtlasApp> {
  late Strings _strings = Strings(pickLanguage(null, _platformLanguage));
  Session? _session;
  Api? _api;
  Object? _error;

  String get _platformLanguage =>
      widget.platformLanguage ?? WidgetsBinding.instance.platformDispatcher.locale.languageCode;

  @override
  void initState() {
    super.initState();
    unawaited(_boot());
  }

  Future<void> _boot() async {
    setState(() => _error = null);
    try {
      final config = await fetchPublicConfig(widget.httpClient, widget.apiBase);
      final strings = Strings(pickLanguage(config.language, _platformLanguage));
      final session = Session(widget.authFactory(config, strings));
      await session.restore();
      if (!mounted) return;
      setState(() {
        _strings = strings;
        _session = session;
        _api = Api(widget.apiBase, session, client: widget.httpClient);
      });
    } on Exception catch (e) {
      if (mounted) setState(() => _error = e);
    }
  }

  @override
  void dispose() {
    _session?.dispose();
    super.dispose();
  }

  Widget _home(BuildContext context) {
    final s = _strings;
    final session = _session;
    final api = _api;
    if (session == null || api == null) {
      return Scaffold(
        body: Center(
          child: _error == null
              ? Column(mainAxisSize: MainAxisSize.min, children: [
                  const CircularProgressIndicator(),
                  const SizedBox(height: 12),
                  Text(s.t('boot.loading')),
                ])
              : Column(mainAxisSize: MainAxisSize.min, children: [
                  Text(s.t('boot.failed',
                      {'url': widget.apiBase, 'error': describeError(_error!, s)})),
                  const SizedBox(height: 12),
                  FilledButton(onPressed: _boot, child: Text(s.t('boot.retry'))),
                ]),
        ),
      );
    }
    return ListenableBuilder(
      listenable: session,
      builder: (context, _) {
        if (session.signedIn) return AppShell(api: api);
        final source = session.source;
        return switch (session.mode) {
          AuthMode.oidc => OidcSignInScreen(session: session),
          AuthMode.token => TokenSignInScreen(
              session: session, tokenPath: source is TokenFileAuth ? source.path : null),
        };
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    ThemeData theme(Brightness b) => ThemeData(
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF2457C5), brightness: b),
          useMaterial3: true,
          visualDensity: VisualDensity.compact,
        );
    return I18n(
      strings: _strings,
      child: MaterialApp(
        title: 'code-atlas',
        debugShowCheckedModeBanner: false,
        theme: theme(Brightness.light),
        darkTheme: theme(Brightness.dark),
        home: Builder(builder: _home),
      ),
    );
  }
}
