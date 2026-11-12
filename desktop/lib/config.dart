/// Compile-time settings of the desktop app (no secret here).
///
/// Only the API base URL is fixed at build time (`--dart-define=ATLAS_API=…`); everything else
/// (sign-in mode, OIDC issuer and client, language) comes from `GET /v1/public-config` at start.
/// In token mode the token file can be moved with `--dart-define=ATLAS_TOKEN_FILE=…`.
library;

const apiBase = String.fromEnvironment('ATLAS_API', defaultValue: 'http://127.0.0.1:8790');

const tokenFileOverride = String.fromEnvironment('ATLAS_TOKEN_FILE');

/// Where the API token is read from, `~` resolved against `$HOME` at run time.
///
/// `null` when the path depends on `$HOME` and it is not set.
String? tokenFilePath(Map<String, String> environment, {String override = tokenFileOverride}) {
  final home = environment['HOME'];
  final raw = override.isNotEmpty ? override : '~/.config/code-atlas/api-token';
  if (raw == '~' || raw.startsWith('~/')) {
    if (home == null || home.isEmpty) return null;
    return '$home${raw.substring(1)}';
  }
  return raw;
}
