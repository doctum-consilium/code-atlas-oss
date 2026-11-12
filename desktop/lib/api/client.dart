/// code-atlas API client: the session's token on every request, readable errors.
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../auth/session.dart';
import 'events.dart';
import 'models.dart';

/// An HTTP error of the API; [detail] is the server's explanation when it gave one.
class ApiException implements Exception {
  ApiException(this.status, this.detail);
  final int status;
  final String? detail;

  static ApiException fromBody(int status, String body) {
    try {
      final detail = (jsonDecode(body) as Json)['detail'];
      if (detail is String) return ApiException(status, detail);
    } on Object {
      // unreadable body: no detail
    }
    return ApiException(status, null);
  }

  @override
  String toString() => detail ?? 'HTTP $status';
}

/// `GET /v1/public-config`: how to sign in, and in which language. Needs no token.
Future<PublicConfig> fetchPublicConfig(http.Client client, String base) async {
  final r = await client.get(Uri.parse('$base/v1/public-config'));
  if (r.statusCode != 200) throw ApiException.fromBody(r.statusCode, r.body);
  return PublicConfig.fromJson(jsonDecode(utf8.decode(r.bodyBytes)) as Json);
}

class Api {
  Api(this.base, this.session, {http.Client? client}) : _http = client ?? http.Client();

  final String base;
  final Session session;
  final http.Client _http;

  Future<Map<String, String>> _headers() async {
    final token = await session.accessToken();
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Bearer $token',
    };
  }

  Object? _read(http.Response r) {
    if (r.statusCode == 401) session.forget();
    if (r.statusCode >= 400) throw ApiException.fromBody(r.statusCode, r.body);
    return r.body.isEmpty ? null : jsonDecode(utf8.decode(r.bodyBytes));
  }

  Future<Object?> _get(String path, [Map<String, String>? query]) async => _read(await _http
      .get(Uri.parse('$base$path').replace(queryParameters: query), headers: await _headers()));

  Future<Object?> _post(String path, [Json? body]) async => _read(await _http.post(
      Uri.parse('$base$path'),
      headers: await _headers(),
      body: body == null ? null : jsonEncode(body)));

  Future<Me> me() async => Me.fromJson(await _get('/v1/me') as Json);
  Future<Facets> facets() async => Facets.fromJson(await _get('/v1/facets') as Json);
  Future<Models> models() async => Models.fromJson(await _get('/v1/models') as Json);
  Future<IndexStatus> indexStatus() async =>
      IndexStatus.fromJson(await _get('/v1/index') as Json);
  Future<IndexStatus> startIndex() async =>
      IndexStatus.fromJson(await _post('/v1/index') as Json);

  Future<List<Repo>> repos() async =>
      (await _get('/v1/repos') as List<dynamic>).map((e) => Repo.fromJson(e as Json)).toList();

  Future<List<ConversationSummary>> conversations() async =>
      (await _get('/v1/conversations') as List<dynamic>)
          .map((e) => ConversationSummary.fromJson(e as Json))
          .toList();

  Future<List<Message>> conversation(String conversationId) async {
    final j = await _get('/v1/conversations/${Uri.encodeComponent(conversationId)}') as Json;
    return (j['messages'] as List<dynamic>).map((e) => Message.fromJson(e as Json)).toList();
  }

  Future<SearchResult> search(String question, Filters filters, {String mode = 'hybrid'}) async =>
      SearchResult.fromJson(await _post('/v1/search', {
        'question': question,
        'filters': filters.toJson(),
        'k': 10,
        'mode': mode,
      }) as Json);

  Future<FileContent> file(String repo, String path) async =>
      FileContent.fromJson(await _get('/v1/files', {'repo': repo, 'path': path}) as Json);

  /// Asks a question; the events arrive while the answer is written.
  Stream<ChatEvent> ask({
    required String question,
    required String mode,
    required String model,
    required Filters filters,
    String? conversationId,
  }) async* {
    final request = http.Request('POST', Uri.parse('$base/v1/chat'))
      ..headers.addAll(await _headers())
      ..body = jsonEncode({
        'question': question,
        'mode': mode,
        'model': model,
        'filters': filters.toJson(),
        'conversation_id': ?conversationId,
      });
    final response = await _http.send(request);
    if (response.statusCode != 200) {
      final body = await response.stream.bytesToString();
      if (response.statusCode == 401) session.forget();
      throw ApiException.fromBody(response.statusCode, body);
    }
    Iterable<ChatEvent> typed(List<SseEvent> events) => events.map(ChatEvent.from).nonNulls;
    var buffer = '';
    await for (final piece in response.stream.transform(utf8.decoder)) {
      buffer += piece;
      final parsed = parseSse(buffer);
      buffer = parsed.rest;
      yield* Stream.fromIterable(typed(parsed.events));
    }
    yield* Stream.fromIterable(typed(parseSse('$buffer\n\n').events));
  }

  void close() => _http.close();
}
