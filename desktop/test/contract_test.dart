/// The desktop app reads only what the contract promises: every route it calls and every field
/// read by lib/api/models.dart must exist in contract/openapi.yaml. A field renamed on the server
/// breaks this test, not the application on the user's machine.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

final contract = loadYaml(File('../contract/openapi.yaml').readAsStringSync()) as YamlMap;
final schemas = (contract['components'] as YamlMap)['schemas'] as YamlMap;
final paths = contract['paths'] as YamlMap;

YamlMap schema(String name) => schemas[name] as YamlMap;

Set<String> fields(String name) =>
    (schema(name)['properties'] as YamlMap).keys.cast<String>().toSet();

List<String> enumOf(String name, String field) =>
    (((schema(name)['properties'] as YamlMap)[field] as YamlMap)['enum'] as YamlList)
        .cast<String>()
        .toList();

YamlMap operation(String path, String method) => (paths[path] as YamlMap)[method] as YamlMap;

Set<String> parameters(String path, String method, String location) =>
    ((operation(path, method)['parameters'] as YamlList?) ?? YamlList())
        .cast<YamlMap>()
        .where((p) => p['in'] == location)
        .map((p) => p['name'] as String)
        .toSet();

/// Fields read by lib/api/models.dart, per contract schema.
const read = {
  'PublicConfig': {'auth_mode', 'language', 'oidc'},
  'OidcPublic': {'issuer', 'desktop_client'},
  'ChunkOut': {'id', 'repo', 'path', 'language', 'type', 'kind', 'symbol', 'line_start', 'line_end',
    'text', 'url', 'score', 'local_only'},
  'Me': {'email', 'admin'},
  'Facets': {'repos', 'languages', 'types', 'owners'},
  'LocalModel': {'name', 'installed', 'default'},
  'RemoteModel': {'alias', 'provider', 'allowed', 'reason', 'verified_on', 'warning'},
  'Models': {'local', 'gateway', 'gateway_enabled'},
  'RepoOut': {'key', 'commit', 'files', 'chunks', 'indexed_at', 'local_only'},
  'IndexStatus': {'running', 'message'},
  'ConversationSummary': {'id', 'title', 'created_at'},
  'Message': {'role', 'content', 'model'},
  'FileOut': {'content', 'language', 'masked_lines'},
  'SearchResponse': {'results', 'duration_ms'},
};

void main() {
  test('every route called by the app exists with its method', () {
    const routes = {
      '/v1/public-config': 'get',
      '/v1/me': 'get',
      '/v1/facets': 'get',
      '/v1/models': 'get',
      '/v1/index': ['get', 'post'],
      '/v1/repos': 'get',
      '/v1/conversations': 'get',
      '/v1/conversations/{conversation_id}': 'get',
      '/v1/search': 'post',
      '/v1/files': 'get',
      '/v1/chat': 'post',
    };
    for (final MapEntry(key: path, value: methods) in routes.entries) {
      expect(paths[path], isNotNull, reason: path);
      for (final m in methods is List<String> ? methods : [methods as String]) {
        expect((paths[path] as YamlMap).containsKey(m), isTrue, reason: '$m $path');
      }
    }
  });

  test('public-config needs no token, and the file route takes repo and path', () {
    expect(parameters('/v1/public-config', 'get', 'header'), isEmpty);
    expect(parameters('/v1/files', 'get', 'query'), containsAll(['repo', 'path']));
    expect(parameters('/v1/conversations/{conversation_id}', 'get', 'path'), {'conversation_id'});
  });

  test('every field read by lib/api/models.dart exists in the contract', () {
    for (final MapEntry(key: name, value: names) in read.entries) {
      expect(fields(name), containsAll(names), reason: name);
    }
    expect(fields('Conversation'), contains('messages'));
  });

  test('the list above covers every key models.dart reads', () {
    final source = File('lib/api/models.dart').readAsStringSync();
    final keys = RegExp(r"j\['(\w+)'\]").allMatches(source).map((m) => m[1]!).toSet();
    final listed = read.values.expand((s) => s).toSet();
    expect(listed, containsAll(keys), reason: 'a key read in models.dart is missing from `read`');
  });

  test('request bodies sent by the app match the contract', () {
    expect(fields('SearchRequest'), containsAll(['question', 'filters', 'k', 'mode']));
    expect(enumOf('SearchRequest', 'mode'), containsAll(['hybrid', 'lexical', 'vector']));
    expect(fields('QuestionRequest'),
        containsAll(['question', 'mode', 'model', 'filters', 'conversation_id']));
    expect(enumOf('QuestionRequest', 'mode'), containsAll(['local', 'gateway']));
    expect(fields('Filters'), containsAll(['repos', 'languages', 'types', 'owners']));
    expect(enumOf('PublicConfig', 'auth_mode'), containsAll(['token', 'oidc']));
    expect(enumOf('PublicConfig', 'language'), containsAll(['en', 'fr']));
  });
}
