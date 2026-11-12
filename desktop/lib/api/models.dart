/// Shapes returned by the API (see contract/openapi.yaml; test/contract_test.dart checks that
/// every field read here exists in the contract).
library;

typedef Json = Map<String, dynamic>;

class OidcPublic {
  OidcPublic.fromJson(Json j)
      : issuer = j['issuer'] as String,
        desktopClient = j['desktop_client'] as String;
  final String issuer, desktopClient;
}

/// `GET /v1/public-config`, served without a token.
class PublicConfig {
  PublicConfig.fromJson(Json j)
      : authMode = j['auth_mode'] as String,
        language = j['language'] as String,
        oidc = j['oidc'] == null ? null : OidcPublic.fromJson(j['oidc'] as Json);
  final String authMode, language;
  final OidcPublic? oidc;
}

class Chunk {
  Chunk.fromJson(Json j)
      : id = j['id'] as int,
        repo = j['repo'] as String,
        path = j['path'] as String,
        language = j['language'] as String,
        type = j['type'] as String,
        kind = j['kind'] as String,
        symbol = j['symbol'] as String?,
        lineStart = j['line_start'] as int,
        lineEnd = j['line_end'] as int,
        text = j['text'] as String,
        url = j['url'] as String?,
        score = (j['score'] as num).toDouble(),
        localOnly = j['local_only'] as bool;

  final int id;
  final String repo, path, language, type, kind, text;
  final String? symbol, url;
  final int lineStart, lineEnd;
  final double score;
  final bool localOnly;

  /// Notebook chunks count cells, not lines.
  bool get isCell => kind == 'cell';
}

class Me {
  Me.fromJson(Json j)
      : email = j['email'] as String,
        admin = j['admin'] as bool;
  final String email;
  final bool admin;
}

class Facets {
  Facets.fromJson(Json j)
      : repos = _strings(j['repos']),
        languages = _strings(j['languages']),
        types = _strings(j['types']),
        owners = _strings(j['owners']);
  final List<String> repos, languages, types, owners;
}

class Filters {
  const Filters({
    this.repos = const {},
    this.languages = const {},
    this.types = const {},
    this.owners = const {},
  });
  final Set<String> repos, languages, types, owners;

  int get count => repos.length + languages.length + types.length + owners.length;

  Json toJson() => {
        'repos': repos.toList(),
        'languages': languages.toList(),
        'types': types.toList(),
        'owners': owners.toList(),
      };

  Filters toggle(String group, String value) {
    Set<String> flip(Set<String> s) =>
        s.contains(value) ? ({...s}..remove(value)) : {...s, value};
    return Filters(
      repos: group == 'repos' ? flip(repos) : repos,
      languages: group == 'languages' ? flip(languages) : languages,
      types: group == 'types' ? flip(types) : types,
      owners: group == 'owners' ? flip(owners) : owners,
    );
  }
}

class LocalModel {
  LocalModel.fromJson(Json j)
      : name = j['name'] as String,
        installed = j['installed'] as bool,
        isDefault = j['default'] as bool;
  final String name;
  final bool installed, isDefault;
}

class RemoteModel {
  RemoteModel.fromJson(Json j)
      : alias = j['alias'] as String,
        provider = j['provider'] as String,
        allowed = j['allowed'] as bool,
        reason = j['reason'] as String,
        verifiedOn = j['verified_on'] as String,
        warning = j['warning'] as String?;
  final String alias, provider, reason, verifiedOn;
  final bool allowed;
  final String? warning;
}

class Models {
  Models.fromJson(Json j)
      : local = _list(j['local'], LocalModel.fromJson),
        gateway = _list(j['gateway'], RemoteModel.fromJson),
        gatewayEnabled = j['gateway_enabled'] as bool;
  final List<LocalModel> local;
  final List<RemoteModel> gateway;
  final bool gatewayEnabled;

  /// The gateway models that may be offered: gateway on, and allowed by the policy.
  List<RemoteModel> get offeredGateway =>
      gatewayEnabled ? gateway.where((m) => m.allowed).toList() : const [];
}

class Repo {
  Repo.fromJson(Json j)
      : key = j['key'] as String,
        commit = j['commit'] as String,
        files = j['files'] as int,
        chunks = j['chunks'] as int,
        indexedAt = j['indexed_at'] as String,
        localOnly = j['local_only'] as bool;
  final String key, commit, indexedAt;
  final int files, chunks;
  final bool localOnly;
}

class IndexStatus {
  IndexStatus.fromJson(Json j)
      : running = j['running'] as bool,
        message = j['message'] as String?;
  final bool running;
  final String? message;
}

class ConversationSummary {
  ConversationSummary.fromJson(Json j)
      : id = j['id'] as String,
        title = j['title'] as String,
        createdAt = j['created_at'] as String;
  final String id, title, createdAt;
}

class Message {
  Message.fromJson(Json j)
      : role = j['role'] as String,
        content = j['content'] as String,
        model = j['model'] as String?;
  final String role, content;
  final String? model;
}

class FileContent {
  FileContent.fromJson(Json j)
      : content = j['content'] as String,
        language = j['language'] as String,
        maskedLines = (j['masked_lines'] as List<dynamic>).cast<int>();
  final String content, language;
  final List<int> maskedLines;
}

class SearchResult {
  SearchResult.fromJson(Json j)
      : results = _list(j['results'], Chunk.fromJson),
        durationMs = j['duration_ms'] as int;
  final List<Chunk> results;
  final int durationMs;
}

List<String> _strings(Object? v) => (v as List<dynamic>).cast<String>();

List<T> _list<T>(Object? v, T Function(Json) f) =>
    (v as List<dynamic>).map((e) => f(e as Json)).toList();
