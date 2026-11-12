# code-atlas desktop

Linux desktop client of code-atlas: hybrid code search and questions over your own repositories.

## Build and run

```sh
flutter build linux --release --dart-define=ATLAS_API=http://127.0.0.1:8790
```

Only the API base URL is set at build time (`ATLAS_API`, default `http://127.0.0.1:8790`). At start
the app reads `GET /v1/public-config` and follows the server:

- `auth_mode: oidc`: sign-in in the system browser (authorization code + PKCE, loopback redirect,
  no client secret), with the server's `oidc.issuer` and `oidc.desktop_client`;
- `auth_mode: token`: the API token is read from `~/.config/code-atlas/api-token` (another path with
  `--dart-define=ATLAS_TOKEN_FILE=…`); when it cannot be read, the token can be pasted on the
  sign-in screen.

Tokens stay in memory only. The interface language (English or French) is the server's
`language`, or the platform locale when the server cannot be reached.

## Tests

```sh
flutter analyze --fatal-infos
flutter test
```

`test/contract_test.dart` checks every route and field used against `../contract/openapi.yaml`.
