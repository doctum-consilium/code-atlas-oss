import '../api/client.dart';
import '../api/models.dart';
import '../auth/oidc.dart';
import '../i18n.dart';

/// An error as the user should read it, in the interface language.
String describeError(Object error, Strings s) => switch (error) {
      ApiException(:final detail?) => detail,
      ApiException(status: 429) => s.t('error.tooMany'),
      ApiException(:final status) => s.t('error.http', {'status': status}),
      LoginException() => error.describe(s),
      _ => error.toString(),
    };

/// "owner/repo/path · lines 3–9" (notebook chunks count cells).
String chunkLabel(Chunk c, Strings s) => s.t(c.isCell ? 'chunk.cells' : 'chunk.lines', {
      'location': '${c.repo}/${c.path}',
      'start': c.lineStart,
      'end': c.lineEnd,
    });
