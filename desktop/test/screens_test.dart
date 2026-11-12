/// Widget tests. No real socket and no real HTTP: the backend is a MockClient and sign-in goes
/// through a fake auth source (the widget test binding blocks real HTTP and loopback servers;
/// the real OIDC flow is tested in logic_test.dart).
library;

import 'dart:convert';
import 'dart:io';

import 'package:code_atlas/api/models.dart';
import 'package:code_atlas/app.dart';
import 'package:code_atlas/auth/oidc.dart';
import 'package:code_atlas/auth/session.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fixtures.dart';

Future<void> mount(WidgetTester tester, FakeBackend backend, AuthSource auth,
    {String platformLanguage = 'en'}) async {
  tester.view.physicalSize = const Size(1800, 1100);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(CodeAtlasApp(
    apiBase: testApi,
    httpClient: backend.client(),
    authFactory: (_, _) => auth,
    platformLanguage: platformLanguage,
  ));
  await tester.pumpAndSettle();
}

/// Signed in from the start (OIDC mode, fake source).
Future<FakeBackend> signedIn(WidgetTester tester, {FakeAuth? auth, bool forbidIndexOnce = false}) async {
  final backend = FakeBackend(config: publicConfigJson(), forbidIndexOnce: forbidIndexOnce);
  await mount(tester, backend, auth ?? FakeAuth(restoreToken: 'A0'));
  return backend;
}

void main() {
  testWidgets('OIDC mode: the sign-in screen shows a readable error', (tester) async {
    final auth = FakeAuth(failure: LoginException(LoginError.noBrowser));
    await mount(tester, FakeBackend(config: publicConfigJson()), auth);
    expect(find.text('Sign in with your identity provider'), findsOneWidget);
    await tester.tap(find.text('Sign in with your identity provider'));
    await tester.pumpAndSettle();
    expect(find.text('No browser could be opened on this machine.'), findsOneWidget);
    expect(auth.logins, [false]);
  });

  testWidgets('OIDC mode: signing in opens the application', (tester) async {
    final backend = FakeBackend(config: publicConfigJson());
    await mount(tester, backend, FakeAuth());
    await tester.tap(find.text('Sign in with your identity provider'));
    await tester.pumpAndSettle();
    expect(find.text('user@example.org'), findsOneWidget);
    expect(find.text('Older question'), findsOneWidget);
    final me = backend.requests.firstWhere((r) => r.url.path == '/v1/me');
    expect(me.headers['Authorization'], 'Bearer A1');
  });

  testWidgets('token mode: the token file signs in without any screen', (tester) async {
    final backend = FakeBackend(config: publicConfigJson(mode: 'token'));
    final auth = TokenFileAuth('/token-file', read: (path) async {
      expect(path, '/token-file');
      return 'file-token\n';
    });
    await mount(tester, backend, auth);
    expect(find.text('user@example.org'), findsOneWidget);
    expect(backend.requests.firstWhere((r) => r.url.path == '/v1/me').headers['Authorization'],
        'Bearer file-token');
  });

  testWidgets('token mode: missing file shows the sign-in screen, a pasted token signs in',
      (tester) async {
    final backend = FakeBackend(config: publicConfigJson(mode: 'token'));
    final auth = TokenFileAuth('/missing/api-token',
        read: (path) async => throw const FileSystemException('not found'));
    await mount(tester, backend, auth);
    expect(find.textContaining('/missing/api-token'), findsOneWidget);
    final field = tester.widget<TextField>(find.byKey(const Key('token')));
    expect(field.obscureText, isTrue);
    await tester.tap(find.text('Sign in'));
    await tester.pumpAndSettle();
    expect(find.text('Paste an API token to sign in.'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('token')), 'pasted-token');
    await tester.tap(find.text('Sign in'));
    await tester.pumpAndSettle();
    expect(find.text('user@example.org'), findsOneWidget);
    expect(backend.requests.firstWhere((r) => r.url.path == '/v1/me').headers['Authorization'],
        'Bearer pasted-token');
  });

  testWidgets('server unreachable: message and retry', (tester) async {
    final backend = FakeBackend();
    await mount(tester, backend, FakeAuth());
    expect(find.textContaining('cannot be reached'), findsOneWidget);
    backend.config = publicConfigJson();
    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('Sign in with your identity provider'), findsOneWidget);
  });

  testWidgets('French from public-config', (tester) async {
    await mount(tester, FakeBackend(config: publicConfigJson(language: 'fr')), FakeAuth());
    expect(find.text("Se connecter avec le fournisseur d'identité"), findsOneWidget);
  });

  testWidgets('platform language while the server cannot be reached', (tester) async {
    await mount(tester, FakeBackend(), FakeAuth(), platformLanguage: 'fr');
    expect(find.text('Réessayer'), findsOneWidget);
  });

  testWidgets('question, streamed answer, [n] citations, sources, source panel', (tester) async {
    final backend = await signedIn(tester);
    await tester.enterText(find.byKey(const Key('question')), 'who receives the feed?');
    await tester.tap(find.text('Ask'));
    await tester.pumpAndSettle();

    final chat = jsonDecode(backend.bodies[backend.requests.indexWhere((r) => r.url.path == '/v1/chat')]) as Json;
    expect(chat, containsPair('mode', 'local'));
    expect(chat, containsPair('model', 'qwen2.5-coder:14b'));
    expect(chat['filters'], containsPair('owners', <String>[]));

    expect(find.textContaining('Only the holder [1] receives the feed [2].', findRichText: true),
        findsOneWidget);
    expect(find.text('Citations without a matching source: [7]'), findsOneWidget);

    // Citation [2]: a chunk without url hides "Open source".
    final markdown = tester.widget<MarkdownBody>(find.byType(MarkdownBody));
    markdown.onTapLink!('[2]', 'chunk:2', '');
    await tester.pumpAndSettle();
    expect(find.text('acme/api/app/f2.py · lines 1–3'), findsOneWidget);
    expect(find.text('Open source'), findsNothing);

    // Citation [1] has a url.
    markdown.onTapLink!('[1]', 'chunk:1', '');
    await tester.pumpAndSettle();
    expect(find.text('Open source'), findsOneWidget);

    // Sources list, then the whole file with line numbers.
    await tester.tap(find.text('Sources (2)'));
    await tester.pumpAndSettle();
    expect(find.textContaining('[2] acme/api/app/f2.py'), findsOneWidget);
    await tester.tap(find.textContaining('[1] acme/api/app/f1.py'));
    await tester.pumpAndSettle();
    expect(tester.widget<Text>(find.byKey(const Key('line-numbers'))).data, '1\n2\n3');
    await tester.tap(find.text('Show whole file'));
    await tester.pumpAndSettle();
    expect(backend.requests.last.url.queryParameters, {'repo': 'acme/api', 'path': 'app/f1.py'});
    expect(find.text('Lines holding secrets are masked: 2'), findsOneWidget);
    expect(find.text('Show whole file'), findsNothing);
    expect(tester.widget<Text>(find.byKey(const Key('line-numbers'))).data, '1\n2\n3\n4');
  });

  testWidgets('model list: local models and allowed gateway models only; banner for remote',
      (tester) async {
    final backend = await signedIn(tester);
    expect(find.byKey(const Key('remote-banner')), findsNothing);
    await tester.tap(find.byKey(const Key('model')));
    await tester.pumpAndSettle();
    expect(find.text('llama3:8b · local (not installed)'), findsWidgets);
    expect(find.textContaining('chat-big'), findsNothing);
    await tester.tap(find.text('coder-30b · example-cloud zero retention').last);
    await tester.pumpAndSettle();
    expect(find.text('Code extracts are sent to example-cloud (zero retention, checked on 2026-11-01).'),
        findsOneWidget);

    await tester.enterText(find.byKey(const Key('question')), 'q');
    await tester.tap(find.text('Ask'));
    await tester.pumpAndSettle();
    final chat = jsonDecode(backend.bodies[backend.requests.indexWhere((r) => r.url.path == '/v1/chat')]) as Json;
    expect(chat, containsPair('mode', 'gateway'));
    expect(chat, containsPair('model', 'coder-30b'));
    expect(find.text('coder-30b · gateway, zero retention'), findsOneWidget);
  });

  testWidgets('search with a mode, then the repositories tab', (tester) async {
    final backend = await signedIn(tester);
    await tester.tap(find.text('Search').first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('search-mode')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Exact words').last);
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('search')), 'can_receive');
    await tester.tap(find.widgetWithText(FilledButton, 'Search'));
    await tester.pumpAndSettle();
    expect(find.text('2 chunks in 9 ms'), findsOneWidget);
    final body = jsonDecode(backend.bodies[backend.requests.indexWhere((r) => r.url.path == '/v1/search')]) as Json;
    expect(body, containsPair('mode', 'lexical'));
    expect(body, containsPair('question', 'can_receive'));

    await tester.tap(find.text('Repositories'));
    await tester.pumpAndSettle();
    expect(find.text('1 repositories · 40 chunks'), findsOneWidget);
    expect(find.text('Update the index'), findsOneWidget);
  });

  testWidgets('admin re-index answered 403: sign in again with prompt=login, retry once',
      (tester) async {
    final auth = FakeAuth(restoreToken: 'A0');
    final backend = await signedIn(tester, auth: auth, forbidIndexOnce: true);
    await tester.tap(find.text('Repositories'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('reindex')));
    await tester.pumpAndSettle();
    expect(auth.logins, [true]);
    expect(backend.count('POST', '/v1/index'), 2);
    final retry = backend.requests.lastWhere((r) => r.method == 'POST' && r.url.path == '/v1/index');
    expect(retry.headers['Authorization'], 'Bearer A1');
    expect(find.text('recent login required'), findsNothing);
    expect(find.text('user@example.org'), findsOneWidget);
  });

  testWidgets('signing out forgets the token and returns to the sign-in screen', (tester) async {
    await signedIn(tester);
    await tester.tap(find.byIcon(Icons.logout));
    await tester.pumpAndSettle();
    expect(find.text('Sign in with your identity provider'), findsOneWidget);
  });
}
