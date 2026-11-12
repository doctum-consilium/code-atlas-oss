/// Shared test data and fakes. Nothing here opens a socket or touches the network.
library;

import 'dart:convert';

import 'package:code_atlas/api/models.dart';
import 'package:code_atlas/auth/oidc.dart';
import 'package:code_atlas/auth/session.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

const issuer = 'https://id.example.com/realms/demo';
const testApi = 'http://api.test';

Json chunkJson(int n, {String? url = 'https://git.example.com/acme/api/blob/abc/app/f.py#L1'}) => {
      'id': n,
      'repo': 'acme/api',
      'path': 'app/f$n.py',
      'language': 'python',
      'type': 'code',
      'kind': 'function',
      'symbol': 'f$n',
      'line_start': 1,
      'line_end': 3,
      'text': 'def f$n():\n    pass\n',
      'url': url,
      'score': 1.5,
      'local_only': false,
      'ranks': <String, int>{},
    };

Json publicConfigJson({String mode = 'oidc', String language = 'en'}) => {
      'auth_mode': mode,
      'language': language,
      'oidc': mode == 'oidc'
          ? {'issuer': issuer, 'web_client': 'code-atlas-web', 'desktop_client': 'code-atlas-desktop'}
          : null,
    };

const modelsJson = {
  'local': [
    {'name': 'qwen2.5-coder:14b', 'installed': true, 'default': true},
    {'name': 'llama3:8b', 'installed': false, 'default': false},
  ],
  'gateway': [
    {
      'alias': 'coder-30b',
      'provider': 'example-cloud',
      'allowed': true,
      'reason': 'zero retention',
      'verified_on': '2026-11-01',
      'source': 'https://example.org/policy',
      'warning': null,
    },
    {
      'alias': 'chat-big',
      'provider': 'other-cloud',
      'allowed': false,
      'reason': 'keeps prompts',
      'verified_on': '2026-11-01',
      'source': 'https://example.org/policy',
    },
  ],
  'gateway_enabled': true,
};

String sse(String name, Object data) => 'event: $name\ndata: ${jsonEncode(data)}\n\n';

const conversationId = '22222222-2222-2222-2222-222222222222';

String chatStream({bool remote = false}) =>
    sse('chunks', {
      'conversation_id': conversationId,
      'model': remote ? 'coder-30b' : 'qwen2.5-coder:14b',
      'provider': remote ? 'example-cloud' : 'local',
      'remote': remote,
      'chunks': [chunkJson(1), chunkJson(2, url: null)],
    }) +
    sse('token', {'text': 'Only the holder [1] receives '}) +
    sse('token', {'text': 'the feed [2].'}) +
    sse('done', {'conversation_id': conversationId, 'citations': <Object>[], 'invalid_citations': [7]});

/// A fake backend: answers every route the app calls, and records the requests.
class FakeBackend {
  FakeBackend({this.config, this.forbidIndexOnce = false, this.admin = true});

  Json? config;
  bool forbidIndexOnce;
  final bool admin;
  final List<http.BaseRequest> requests = [];
  final List<String> bodies = [];

  int count(String method, String path) =>
      requests.where((r) => r.method == method && r.url.path == path).length;

  http.Client client() => MockClient.streaming((r, bodyStream) async {
        requests.add(r);
        bodies.add(await bodyStream.bytesToString());
        http.StreamedResponse json(Object o, [int status = 200]) =>
            http.StreamedResponse(Stream.value(utf8.encode(jsonEncode(o))), status);
        switch ((r.method, r.url.path)) {
          case ('GET', '/v1/public-config'):
            final c = config;
            return c == null ? json({'detail': 'down'}, 503) : json(c);
          case ('GET', '/v1/me'):
            return json({'subject': 's1', 'email': 'user@example.org', 'client': 'code-atlas-desktop', 'admin': admin});
          case ('GET', '/v1/facets'):
            return json({'repos': ['acme/api'], 'languages': ['python'], 'types': ['code'], 'owners': ['acme']});
          case ('GET', '/v1/conversations'):
            return json([
              {'id': '11111111-1111-1111-1111-111111111111', 'title': 'Older question', 'created_at': 'x'},
            ]);
          case ('GET', '/v1/models'):
            return json(modelsJson);
          case ('GET', '/v1/repos'):
            return json([
              {'key': 'acme/api', 'commit': 'abcdef12', 'files': 3, 'chunks': 40, 'indexed_at': 'x', 'local_only': false},
            ]);
          case ('GET', '/v1/index'):
            return json({'running': false, 'message': null});
          case ('POST', '/v1/index'):
            if (forbidIndexOnce) {
              forbidIndexOnce = false;
              return json({'detail': 'recent login required'}, 403);
            }
            return json({'running': false, 'message': 'started'}, 202);
          case ('POST', '/v1/search'):
            return json({'results': [chunkJson(1), chunkJson(2)], 'duration_ms': 9});
          case ('GET', '/v1/files'):
            return json({
              'repo': 'acme/api',
              'path': 'app/f1.py',
              'language': 'python',
              'content': 'import os\nSECRET = "***"\ndef f1():\n    pass',
              'masked_lines': [2],
              'url': null,
            });
          case ('POST', '/v1/chat'):
            final remote = (jsonDecode(bodies.last) as Json)['mode'] == 'gateway';
            return http.StreamedResponse(Stream.value(utf8.encode(chatStream(remote: remote))), 200);
        }
        return json({'detail': 'unknown'}, 404);
      });
}

/// A fake auth source: no browser, no loopback server. Records each interactive login.
class FakeAuth implements AuthSource {
  FakeAuth({this.mode = AuthMode.oidc, this.restoreToken, this.failure});

  @override
  final AuthMode mode;
  final String? restoreToken;
  final Exception? failure;

  /// `forceLogin` of each call to [login].
  final List<bool> logins = [];

  static Tokens tokens(String access) =>
      Tokens(access: access, expiresAt: DateTime.now().add(const Duration(hours: 1)));

  @override
  Future<Tokens?> restore() async => restoreToken == null ? null : tokens(restoreToken!);

  @override
  Future<Tokens> login({bool forceLogin = false}) async {
    logins.add(forceLogin);
    final f = failure;
    if (f != null) throw f;
    return tokens('A${logins.length}');
  }

  @override
  Future<Tokens> refresh(String refreshToken) async => tokens('R');
}
