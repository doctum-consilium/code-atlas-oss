/// Session: tokens in memory only, renewed before they expire.
///
/// Nothing is written to disk or to a keyring: closing the application forgets everything. Two
/// sources of tokens, chosen by the server's `auth_mode`:
///  - [OidcAuth]: browser sign-in (PKCE, loopback redirect), tokens renewed by refresh token;
///  - [TokenFileAuth]: a static API token read from a file, or pasted on the sign-in screen.
library;

import 'dart:io';

import 'package:flutter/foundation.dart';

import 'oidc.dart';

enum AuthMode { oidc, token }

/// Where tokens come from.
abstract interface class AuthSource {
  AuthMode get mode;

  /// Tokens available without any interaction (token mode: the token file), or `null`.
  Future<Tokens?> restore();

  /// Interactive sign-in. [forceLogin] asks for the credentials again (recent login).
  Future<Tokens> login({bool forceLogin = false});

  /// Renews expired tokens.
  Future<Tokens> refresh(String refreshToken);
}

/// OIDC through the system browser.
class OidcAuth implements AuthSource {
  OidcAuth(this.client);
  final OidcClient client;

  @override
  AuthMode get mode => AuthMode.oidc;

  @override
  Future<Tokens?> restore() async => null;

  @override
  Future<Tokens> login({bool forceLogin = false}) => client.login(forceLogin: forceLogin);

  @override
  Future<Tokens> refresh(String refreshToken) => client.refresh(refreshToken);
}

typedef ReadFile = Future<String> Function(String path);

Future<String> _readFile(String path) => File(path).readAsString();

/// A static API token. It does not expire, so there is nothing to refresh.
Tokens staticToken(String token) =>
    Tokens(access: token, expiresAt: DateTime.utc(9999));

/// The API token from a file (`~/.config/code-atlas/api-token` by default).
class TokenFileAuth implements AuthSource {
  TokenFileAuth(this.path, {ReadFile? read}) : _read = read ?? _readFile;

  /// `null` when no path could be resolved (no `$HOME`).
  final String? path;
  final ReadFile _read;

  @override
  AuthMode get mode => AuthMode.token;

  /// The token of the file; `null` if it is missing, unreadable or empty.
  @override
  Future<Tokens?> restore() async {
    final p = path;
    if (p == null) return null;
    try {
      final token = (await _read(p)).trim();
      return token.isEmpty ? null : staticToken(token);
    } on Exception {
      return null;
    }
  }

  @override
  Future<Tokens> login({bool forceLogin = false}) async =>
      throw LoginException(LoginError.tokenRequired);

  @override
  Future<Tokens> refresh(String refreshToken) async =>
      throw LoginException(LoginError.tokenRequired);
}

class Session extends ChangeNotifier {
  Session(this.source);

  final AuthSource source;
  Tokens? _tokens;
  Future<Tokens>? _renewal;

  AuthMode get mode => source.mode;
  bool get signedIn => _tokens != null;

  /// Whether a refused admin action can be retried after a fresh sign-in.
  bool get canReauthenticate => source.mode == AuthMode.oidc;

  /// Signs in silently when the source allows it; returns whether it did.
  Future<bool> restore() async {
    final tokens = await source.restore();
    if (tokens == null) return false;
    _set(tokens);
    return true;
  }

  Future<void> login({bool forceLogin = false}) async =>
      _set(await source.login(forceLogin: forceLogin));

  /// Token mode: a token pasted by the user (kept in memory only).
  void useToken(String token) {
    final t = token.trim();
    if (t.isEmpty) throw LoginException(LoginError.tokenRequired);
    _set(staticToken(t));
  }

  void _set(Tokens tokens) {
    _tokens = tokens;
    notifyListeners();
  }

  /// A valid access token, renewed if needed; `null` if the session is lost.
  Future<String?> accessToken() async {
    final current = _tokens;
    if (current == null) return null;
    if (!current.expired) return current.access;
    final refresh = current.refresh;
    if (refresh == null) {
      forget();
      return null;
    }
    try {
      // A single renewal at a time, even when several requests leave together.
      _tokens = await (_renewal ??= source.refresh(refresh));
      return _tokens!.access;
    } on LoginException {
      forget();
      return null;
    } finally {
      _renewal = null;
    }
  }

  void forget() {
    if (_tokens == null) return;
    _tokens = null;
    notifyListeners();
  }
}
