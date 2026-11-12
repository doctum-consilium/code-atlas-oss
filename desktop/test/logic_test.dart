/// Logic without widgets. The real OIDC loopback flow runs here (plain `test`, real loopback
/// server, MockClient for the identity provider): widget tests block real sockets.
library;

import 'dart:convert';
import 'dart:io';

import 'package:code_atlas/api/client.dart';
import 'package:code_atlas/api/events.dart';
import 'package:code_atlas/api/models.dart';
import 'package:code_atlas/auth/oidc.dart';
import 'package:code_atlas/auth/session.dart';
import 'package:code_atlas/citations.dart';
import 'package:code_atlas/config.dart';
import 'package:code_atlas/i18n.dart';
import 'package:code_atlas/screens/common.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'fixtures.dart';

http.Response tokenResponse({int seconds = 300, String access = 'A1', String? refresh = 'R1'}) =>
    http.Response(
        jsonEncode({'access_token': access, 'expires_in': seconds, 'refresh_token': ?refresh}), 200);

/// Plays the identity provider's redirect to the loopback server, with the right `state`.
Future<void> redirectWithCode(String url) async {
  final u = Uri.parse(url);
  await http.get(Uri.parse(u.queryParameters['redirect_uri']!)
      .replace(queryParameters: {'state': u.queryParameters['state'], 'code': 'C'}));
}

void main() {
  group('citations', () {
    test('links valid numbers with their brackets, marks the others, leaves code alone', () {
      expect(linkCitations('A [1], B [3] and `x[1]`', 2), r'A [\[1\]](chunk:1), B [3]⁇ and `x[1]`');
      expect(linkCitations('```\nt[2]\n```\n[2]', 2), '```\nt[2]\n```\n' r'[\[2\]](chunk:2)');
      expect(citationNumber('chunk:4'), 4);
      expect(citationNumber('https://example.org'), isNull);
      expect(citationNumber(null), isNull);
    });
  });

  group('SSE', () {
    test('splits whole events and keeps the rest', () {
      final p = parseSse('event: token\ndata: {"text":"a"}\n\nevent: x\n\nevent: y\ndata: {bad\n\nevent: done');
      expect(p.events.map((e) => e.name), ['token']);
      expect(p.events.single.data['text'], 'a');
      expect(p.rest, 'event: done');
    });

    test('typed events of the new contract', () {
      final events = parseSse(chatStream(remote: true)).events.map(ChatEvent.from).toList();
      final chunks = events[0]! as ChunksEvent;
      expect(chunks.conversationId, conversationId);
      expect(chunks.remote, isTrue);
      expect(chunks.provider, 'example-cloud');
      expect(chunks.chunks.map((c) => c.url), [isNotNull, isNull]);
      expect((events[1]! as TokenEvent).text, startsWith('Only the holder'));
      expect((events[3]! as DoneEvent).invalidCitations, [7]);
      expect(ChatEvent.from(const SseEvent('error', {'reason': 'refused'})), isA<ErrorEvent>());
      expect(ChatEvent.from(const SseEvent('later', {})), isNull);
    });
  });

  group('OIDC', () {
    test('PKCE S256 matches RFC 7636', () {
      expect(OidcClient.challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),
          'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM');
      expect(OidcClient.randomString().length, 64);
    });

    test('the authorization URL carries the challenge, the state and the loopback redirect', () {
      final url = OidcClient(issuer: issuer, clientId: 'code-atlas-desktop').authorizationUrl(
          redirectUri: 'http://127.0.0.1:4000/callback', state: 'S', codeChallenge: 'D', forceLogin: true);
      expect(url.path, '/realms/demo/protocol/openid-connect/auth');
      expect(url.queryParameters, containsPair('code_challenge_method', 'S256'));
      expect(url.queryParameters, containsPair('code_challenge', 'D'));
      expect(url.queryParameters, containsPair('state', 'S'));
      expect(url.queryParameters, containsPair('prompt', 'login'));
      expect(url.queryParameters['redirect_uri'], 'http://127.0.0.1:4000/callback');
    });

    test('full sign-in through the loopback server, no client secret', () async {
      late Map<String, String> exchange;
      late String successPage;
      final oidc = OidcClient(
        issuer: issuer,
        clientId: 'code-atlas-desktop',
        strings: const Strings('fr'),
        httpClient: MockClient((r) async {
          exchange = r.bodyFields;
          return tokenResponse();
        }),
        openBrowser: (url) async {
          final u = Uri.parse(url);
          final back = Uri.parse(u.queryParameters['redirect_uri']!);
          expect(back.host, '127.0.0.1');
          final client = http.Client();
          // An intruder without the right `state` is ignored, then the provider sends the code.
          final intruder = await client.get(back.replace(queryParameters: {'state': 'wrong', 'code': 'X'}));
          expect(intruder.statusCode, 400);
          final ok = await client
              .get(back.replace(queryParameters: {'state': u.queryParameters['state'], 'code': 'C'}));
          successPage = ok.body;
          client.close();
        },
      );
      final t = await oidc.login();
      expect(t.access, 'A1');
      expect(exchange['code'], 'C');
      expect(exchange['grant_type'], 'authorization_code');
      expect(exchange['code_verifier'], hasLength(64));
      expect(exchange.containsKey('client_secret'), isFalse);
      expect(successPage, contains('Connexion réussie'));
      expect(t.toString(), isNot(contains('A1')));
    });

    test('the server listens before the browser opens (fast redirect)', () async {
      final oidc = OidcClient(
        issuer: issuer,
        clientId: 'c',
        httpClient: MockClient((_) async => tokenResponse()),
        // The redirect is sent before openBrowser even returns.
        openBrowser: redirectWithCode,
      );
      expect((await oidc.login()).access, 'A1');
    });

    test('provider refusing the code', () async {
      final oidc = OidcClient(
        issuer: issuer,
        clientId: 'c',
        httpClient: MockClient((_) async => http.Response('{}', 400)),
        openBrowser: redirectWithCode,
      );
      await expectLater(oidc.login(),
          throwsA(isA<LoginException>().having((e) => e.error, 'error', LoginError.tokenRejected)));
    });

    test('error sent back by the provider', () async {
      final oidc = OidcClient(
        issuer: issuer,
        clientId: 'c',
        openBrowser: (url) async {
          final u = Uri.parse(url);
          await http.get(Uri.parse(u.queryParameters['redirect_uri']!)
              .replace(queryParameters: {'state': 'x', 'error': 'access_denied'}));
        },
      );
      await expectLater(oidc.login(),
          throwsA(isA<LoginException>().having((e) => e.detail, 'detail', 'access_denied')));
    });

    test('no browser: the error surfaces and the server is closed', () async {
      final oidc = OidcClient(
          issuer: issuer, clientId: 'c', openBrowser: (_) async => throw LoginException(LoginError.noBrowser));
      await expectLater(oidc.login(), throwsA(isA<LoginException>()));
    });
  });

  group('Session', () {
    test('renews an expired token once, then forgets if the provider refuses', () async {
      var calls = 0;
      var refuse = false;
      final oidc = OidcClient(
        issuer: issuer,
        clientId: 'c',
        httpClient: MockClient((r) async {
          calls++;
          if (refuse) return http.Response('{}', 400);
          return r.bodyFields['grant_type'] == 'refresh_token'
              ? tokenResponse(access: 'A2', seconds: 0)
              : tokenResponse(seconds: 0);
        }),
        openBrowser: redirectWithCode,
      );
      final session = Session(OidcAuth(oidc));
      var notifications = 0;
      session.addListener(() => notifications++);
      expect(await session.restore(), isFalse);
      await session.login();
      expect(session.signedIn, isTrue);
      expect(session.canReauthenticate, isTrue);
      final two = await Future.wait([session.accessToken(), session.accessToken()]);
      expect(two, ['A2', 'A2']);
      expect(calls, 2);
      refuse = true;
      expect(await session.accessToken(), isNull);
      expect(session.signedIn, isFalse);
      expect(notifications, 2);
    });
  });

  group('token mode', () {
    late Directory dir;
    setUp(() async => dir = await Directory.systemTemp.createTemp('code-atlas-test'));
    tearDown(() async => dir.delete(recursive: true));

    test('reads the token file (trimmed), in memory only', () async {
      final file = File('${dir.path}/api-token')..writeAsStringSync('  tok-123\n');
      final session = Session(TokenFileAuth(file.path));
      expect(await session.restore(), isTrue);
      expect(await session.accessToken(), 'tok-123');
      expect(session.mode, AuthMode.token);
      expect(session.canReauthenticate, isFalse);
      expect(dir.listSync(), hasLength(1), reason: 'nothing written next to the token');
    });

    test('missing, empty or unresolvable file: no token', () async {
      expect(await TokenFileAuth('${dir.path}/absent').restore(), isNull);
      final empty = File('${dir.path}/empty')..writeAsStringSync('\n');
      expect(await TokenFileAuth(empty.path).restore(), isNull);
      expect(await TokenFileAuth(null).restore(), isNull);
      await expectLater(TokenFileAuth(null).login(), throwsA(isA<LoginException>()));
    });

    test('a pasted token signs in; an empty one is refused; 401 forgets it', () async {
      final session = Session(TokenFileAuth(null));
      expect(() => session.useToken('   '), throwsA(isA<LoginException>()));
      session.useToken(' pasted ');
      final api = Api(testApi, session,
          client: MockClient((r) async {
            expect(r.headers['Authorization'], 'Bearer pasted');
            return http.Response('{"detail":"bad token"}', 401);
          }));
      await expectLater(api.me(), throwsA(isA<ApiException>()));
      expect(session.signedIn, isFalse);
    });

    test('token file path: \$HOME resolved at run time, override honoured', () {
      expect(tokenFilePath({'HOME': '/u'}, override: ''), '/u/.config/code-atlas/api-token');
      expect(tokenFilePath({}, override: ''), isNull);
      expect(tokenFilePath({'HOME': '/u'}, override: '~/t'), '/u/t');
      expect(tokenFilePath({}, override: '/etc/t'), '/etc/t');
    });
  });

  group('Api', () {
    Future<Session> signedIn() async {
      final s = Session(FakeAuth());
      await s.login();
      return s;
    }

    test('public config without a token', () async {
      final backend = FakeBackend(config: publicConfigJson(mode: 'token', language: 'fr'));
      final c = await fetchPublicConfig(backend.client(), testApi);
      expect(c.authMode, 'token');
      expect(c.language, 'fr');
      expect(c.oidc, isNull);
      expect(backend.requests.single.headers.containsKey('Authorization'), isFalse);
      final oidc = await fetchPublicConfig(FakeBackend(config: publicConfigJson()).client(), testApi);
      expect(oidc.oidc!.desktopClient, 'code-atlas-desktop');
      expect(oidc.oidc!.issuer, issuer);
    });

    test('sends the token and the new field names, reads chunks, forgets on 401', () async {
      final session = await signedIn();
      final requests = <http.Request>[];
      final api = Api(testApi, session, client: MockClient((r) async {
        requests.add(r);
        if (r.url.path == '/v1/search') {
          return http.Response(jsonEncode({'results': [chunkJson(1)], 'duration_ms': 12}), 200);
        }
        if (r.url.path == '/v1/files') {
          return http.Response(
              jsonEncode({'repo': 'acme/api', 'path': 'a b.py', 'language': 'python', 'content': 'x',
                'masked_lines': <int>[], 'url': null}),
              200);
        }
        return http.Response('{"detail":"not authenticated"}', 401);
      }));
      final r = await api.search('q', const Filters(languages: {'python'}), mode: 'lexical');
      expect(r.results.single.repo, 'acme/api');
      expect(r.durationMs, 12);
      expect(chunkLabel(r.results.single, Strings.en), 'acme/api/app/f1.py · lines 1–3');
      expect(requests.first.headers['Authorization'], 'Bearer A1');
      final body = jsonDecode(requests.first.body) as Json;
      expect(body, containsPair('filters', containsPair('languages', ['python'])));
      expect(body, containsPair('mode', 'lexical'));
      expect(body.containsKey('filtres'), isFalse);
      await api.file('acme/api', 'a b.py');
      expect(requests.last.url.queryParameters, {'repo': 'acme/api', 'path': 'a b.py'});
      await expectLater(
          api.me(), throwsA(isA<ApiException>().having((e) => e.detail, 'detail', 'not authenticated')));
      expect(session.signedIn, isFalse);
    });

    test('reads an answer stream split at random places', () async {
      final session = await signedIn();
      final bytes = utf8.encode(chatStream());
      late Json sent;
      final api = Api(testApi, session, client: MockClient.streaming((r, body) async {
        sent = jsonDecode(await body.bytesToString()) as Json;
        final pieces = [
          for (var i = 0; i < bytes.length; i += 5) bytes.sublist(i, (i + 5).clamp(0, bytes.length)),
        ];
        return http.StreamedResponse(Stream.fromIterable(pieces), 200);
      }));
      final events = await api
          .ask(question: 'q', mode: 'local', model: 'm', filters: const Filters())
          .toList();
      expect(events.map((e) => e.runtimeType), [ChunksEvent, TokenEvent, TokenEvent, DoneEvent]);
      expect(sent, containsPair('model', 'm'));
      expect(sent.containsKey('conversation_id'), isFalse);
    });

    test('gives the reason of a refused gateway model', () async {
      final session = await signedIn();
      final api = Api(testApi, session, client: MockClient.streaming((r, _) async =>
          http.StreamedResponse(Stream.value(utf8.encode('{"detail":"alias not in the allow-list"}')), 409)));
      await expectLater(
        api.ask(question: 'q', mode: 'gateway', model: 'x', filters: const Filters()).toList(),
        throwsA(isA<ApiException>().having((e) => e.status, 'status', 409)),
      );
    });

    test('readable errors', () {
      expect(describeError(ApiException(429, null), Strings.en), contains('try again'));
      expect(describeError(ApiException.fromBody(500, 'not json'), Strings.en), 'Error 500');
      expect(describeError(ApiException.fromBody(422, '{"detail":[{"msg":"x"}]}'), const Strings('fr')),
          'Erreur 422');
      expect(describeError(ApiException.fromBody(409, '{"detail":"nope"}'), Strings.en), 'nope');
      expect(describeError(LoginException(LoginError.refused, 'access_denied'), Strings.en),
          contains('access_denied'));
    });
  });

  group('i18n', () {
    final placeholder = RegExp(r'\{(\w+)\}');
    Set<String> holes(String s) => placeholder.allMatches(s).map((m) => m[1]!).toSet();

    test('English and French have the same keys and the same placeholders', () {
      final en = dictionary['en']!, fr = dictionary['fr']!;
      expect(fr.keys.toSet(), en.keys.toSet());
      for (final key in en.keys) {
        expect(holes(fr[key]!), holes(en[key]!), reason: key);
      }
    });

    test('every LoginError has a text', () {
      for (final e in LoginError.values) {
        expect(dictionary['en']!.containsKey('login.${e.name}'), isTrue, reason: e.name);
      }
    });

    test('lookup, substitution and fallbacks', () {
      expect(const Strings('fr').t('search.count', {'count': 2, 'ms': 9}), '2 extraits en 9 ms');
      expect(Strings.en.t('search.count', {'count': 2, 'ms': 9}), '2 chunks in 9 ms');
      expect(const Strings('de').t('search.go'), 'Search');
      expect(Strings.en.t('no.such.key'), 'no.such.key');
    });

    test('language: server first, then platform, then English', () {
      expect(pickLanguage('fr', 'en'), 'fr');
      expect(pickLanguage(null, 'fr'), 'fr');
      expect(pickLanguage(null, 'de'), 'en');
      expect(pickLanguage('xx', 'de'), 'en');
    });
  });

  test('Filters', () {
    final f = const Filters().toggle('types', 'doc').toggle('owners', 'acme').toggle('types', 'doc');
    expect(f.toJson(), {'repos': <String>[], 'languages': <String>[], 'types': <String>[], 'owners': ['acme']});
    expect(f.count, 1);
  });

  test('only allowed gateway models are offered, and none when the gateway is off', () {
    final m = Models.fromJson(modelsJson);
    expect(m.offeredGateway.map((g) => g.alias), ['coder-30b']);
    expect(Models.fromJson({...modelsJson, 'gateway_enabled': false}).offeredGateway, isEmpty);
  });
}
