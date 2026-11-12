# Security

code-atlas reads private source code. Its design goal is that this code stays on your machine
unless you explicitly decide otherwise.

## What the defaults guarantee

| Layer | Default |
|---|---|
| Network | the API, the web front, the database and the model server listen on `127.0.0.1` only; the API refuses any other interface and any foreign `Host` header |
| Access | every API route except `/healthz` and `/v1/public-config` needs a token: a random 256-bit token in a `0600` file (`token` mode), or an OIDC access token checked for issuer, audience, client, type, role, e-mail and expiry (`oidc` mode) |
| Secrets in your code | detect-secrets runs before indexing; flagged lines are replaced by a mask, files holding a private key are skipped entirely; the report shows paths and line numbers, never values |
| Models | embeddings, reranking and the default chat model run locally |
| Remote models | off by default; when enabled, only aliases listed in your policy file (zero data retention providers) receive extracts, and repositories listed in `local_only` never leave the machine |
| Browser | tokens kept in memory only (no localStorage, sessionStorage or cookies), strict Content-Security-Policy, no framing |
| Database | password generated into a `0600` file, never printed |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting ("Report a vulnerability" in the Security tab)
rather than a public issue. Include the version (commit), your settings mode (`token` or `oidc`)
and the steps to reproduce.
