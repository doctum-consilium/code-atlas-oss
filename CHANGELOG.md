# Changelog

All notable changes are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## [1.0.0] — 2026-11-13

First public release: search and question your own repositories, on your own machine.

### Search
- Hybrid retrieval: exact words (BM25, ParadeDB pg_search) + meaning (pgvector HNSW) + exact
  symbol match, fused by Reciprocal Rank Fusion, then a cross-encoder reranks the top 30.
- Chunking along code structure with tree-sitter (functions, methods, `Class.method`), Markdown and
  LaTeX by heading, notebooks by cell; identifier splitting for camelCase and snake_case.
- Incremental indexing: only files whose git hash changed are read again.
- Measured on 40 real questions over ~110 repositories: the right file in the top 10 for 98 % of
  the questions (MRR 0.81).

### Questions
- Answers from a local model (Ollama or any OpenAI-compatible server), streamed, citing
  `repo/path:lines`; every `[n]` citation is checked against the supplied chunks.
- Remote models only through an optional gateway, and only for aliases listed in a written
  zero-data-retention policy; `local_only` repositories never leave the machine.

### Clients
- React web app and Flutter Linux desktop app on the same OpenAPI contract, in English or French.

### Security
- Loopback only, `Host` check, strict CORS and CSP, rate limits.
- Local token (0600 file, constant-time check) or any OIDC provider (PKCE, issuer, audience,
  client, roles claim, allowed e-mails); Keycloak setup script included.
- Secrets masked with detect-secrets before indexing; files with a private key skipped.

### Operations
- One-command installer (`scripts/install.sh`): settings, containers, models, index, builds,
  user services, checks. Thermal guard pauses heavy work above a GPU/CPU temperature.
- CI: lint, strict typing, tests on a real database, contract drift, browser end-to-end in both
  sign-in modes, gitleaks, osv-scanner, leak guard against private terms.

### Release artifacts
- `code_atlas-1.0.0` wheel and sdist, `code-atlas-web-v1.0.0.tar.gz` (static web build),
  `code-atlas-desktop-linux-x64-v1.0.0.tar.gz` (Flutter bundle) and `SHA256SUMS`.
