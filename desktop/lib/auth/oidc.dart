/// Sign-in through the system browser (OIDC authorization code + PKCE, RFC 8252).
///
///  1. the app draws a one-time secret (`code_verifier`) and its digest (`code_challenge`);
///  2. it opens the system browser on the identity provider;
///  3. the provider redirects to `http://127.0.0.1:<port>/callback` (only this machine receives
///     it);
///  4. the app exchanges the code and the `code_verifier` for tokens, with no embedded secret.
///
/// The password (and the second factor) never reach this application.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher_string.dart';

import '../i18n.dart';

/// Tokens, in memory only; [toString] never shows them.
class Tokens {
  const Tokens({required this.access, required this.expiresAt, this.refresh});

  final String access;
  final String? refresh;
  final DateTime expiresAt;

  bool get expired => DateTime.now().isAfter(expiresAt.subtract(const Duration(seconds: 30)));

  @override
  String toString() =>
      'Tokens(refresh: ${refresh == null ? 'absent' : 'present'}, expires: $expiresAt)';
}

/// Why a sign-in failed; the interface turns it into text (`login.<name>` in i18n.dart).
enum LoginError { noBrowser, timeout, refused, tokenRejected, noAccessToken, interrupted, tokenRequired }

class LoginException implements Exception {
  LoginException(this.error, [this.detail]);
  final LoginError error;
  final String? detail;

  String describe(Strings s) => s.t('login.${error.name}', {'detail': detail ?? ''});

  @override
  String toString() => describe(Strings.en);
}

typedef OpenBrowser = Future<void> Function(String url);

class OidcClient {
  OidcClient({
    required this.issuer,
    required this.clientId,
    this.strings = Strings.en,
    http.Client? httpClient,
    OpenBrowser? openBrowser,
  })  : _http = httpClient ?? http.Client(),
        _open = openBrowser ?? _systemBrowser;

  final String issuer;
  final String clientId;

  /// Language of the page shown in the browser after the redirect.
  final Strings strings;
  final http.Client _http;
  final OpenBrowser _open;

  static const _unreserved = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';

  static Future<void> _systemBrowser(String url) async {
    var opened = false;
    try {
      opened = await launchUrlString(url);
    } on Exception {
      opened = false;
    }
    if (!opened) throw LoginException(LoginError.noBrowser);
  }

  static String randomString([int length = 64]) {
    final rnd = Random.secure();
    return String.fromCharCodes(
      List.generate(length, (_) => _unreserved.codeUnitAt(rnd.nextInt(_unreserved.length))),
    );
  }

  /// S256 `code_challenge`: base64url(SHA-256(verifier)), without `=`.
  static String challenge(String verifier) =>
      base64UrlEncode(sha256.convert(ascii.encode(verifier)).bytes).replaceAll('=', '');

  Uri authorizationUrl({
    required String redirectUri,
    required String state,
    required String codeChallenge,
    bool forceLogin = false,
  }) =>
      Uri.parse('$issuer/protocol/openid-connect/auth').replace(queryParameters: {
        'client_id': clientId,
        'redirect_uri': redirectUri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'code_challenge': codeChallenge,
        'code_challenge_method': 'S256',
        if (forceLogin) 'prompt': 'login',
      });

  /// Full flow. [forceLogin] asks for the credentials again (admin actions need a recent login).
  Future<Tokens> login({
    bool forceLogin = false,
    Duration timeout = const Duration(minutes: 3),
  }) async {
    final verifier = randomString();
    final state = randomString(32);
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final redirectUri = 'http://127.0.0.1:${server.port}/callback';
    // Listen BEFORE opening the browser: a fast redirect (provider session already open) must
    // not land on a port nobody reads yet.
    final waiting = _awaitCode(server, state);
    try {
      try {
        await _open(authorizationUrl(
          redirectUri: redirectUri,
          state: state,
          codeChallenge: challenge(verifier),
          forceLogin: forceLogin,
        ).toString());
      } on Object {
        waiting.ignore();
        rethrow;
      }
      final code = await waiting.timeout(
        timeout,
        onTimeout: () => throw LoginException(LoginError.timeout),
      );
      return await _exchange({
        'grant_type': 'authorization_code',
        'client_id': clientId,
        'code': code,
        'redirect_uri': redirectUri,
        'code_verifier': verifier,
      });
    } finally {
      await server.close(force: true);
    }
  }

  String _page(String title, [String? body]) =>
      '<html><body style="font-family:sans-serif"><h3>${_html(title)}</h3>'
      '${body == null ? '' : '<p>${_html(body)}</p>'}</body></html>';

  static String _html(String s) => const HtmlEscape().convert(s);

  Future<String> _awaitCode(HttpServer server, String expectedState) async {
    await for (final request in server) {
      final params = request.uri.queryParameters;
      final ok = params['state'] == expectedState && params['code'] != null;
      request.response
        ..statusCode = ok ? HttpStatus.ok : HttpStatus.badRequest
        ..headers.contentType = ContentType.html
        ..write(ok
            ? _page(strings.t('login.page.success'), strings.t('login.page.close'))
            : _page(strings.t('login.page.refused')));
      await request.response.close();
      if (ok) return params['code']!;
      if (params.containsKey('error')) {
        throw LoginException(LoginError.refused, params['error']);
      }
      // Unexpected `state`: ignore this request and keep waiting (anti-CSRF).
    }
    throw LoginException(LoginError.interrupted);
  }

  /// Renews the access token (public client: no secret).
  Future<Tokens> refresh(String refreshToken) => _exchange({
        'grant_type': 'refresh_token',
        'client_id': clientId,
        'refresh_token': refreshToken,
      }, fallbackRefresh: refreshToken);

  Future<Tokens> _exchange(Map<String, String> body, {String? fallbackRefresh}) async {
    final response = await _http.post(
      Uri.parse('$issuer/protocol/openid-connect/token'),
      headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: body,
    );
    if (response.statusCode != 200) {
      throw LoginException(LoginError.tokenRejected, '${response.statusCode}');
    }
    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final access = data['access_token'];
    if (access is! String || access.isEmpty) throw LoginException(LoginError.noAccessToken);
    final seconds = (data['expires_in'] as num?)?.toInt() ?? 300;
    final refresh = data['refresh_token'];
    return Tokens(
      access: access,
      refresh: refresh is String && refresh.isNotEmpty ? refresh : fallbackRefresh,
      expiresAt: DateTime.now().add(Duration(seconds: seconds)),
    );
  }

  void close() => _http.close();
}
