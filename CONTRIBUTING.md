# Contributing

Thank you for helping. A few rules keep code-atlas safe to run on private code.

## Before a pull request

```bash
git config core.hooksPath .githooks      # leak guard + lint + tests before each commit
bash scripts/ci_local.sh                 # replays the whole CI (needs a test database)
```

A local test database:

```bash
podman run -d --name atlas-test -p 127.0.0.1:55432:5432 -e POSTGRES_USER=atlas \
  -e POSTGRES_PASSWORD=atlas-test -e POSTGRES_DB=atlas_test docker.io/paradedb/paradedb:v0.26.6-pg18
export CODE_ATLAS_TEST_DSN="host=127.0.0.1 port=55432 user=atlas password=atlas-test dbname=atlas_test"
```

## Rules

- **Nothing personal in the repository**: no real names, e-mails, domains or repository names in
  code, tests, fixtures or screenshots. Use `example.org`, `acme/api`. The leak guard
  (`scripts/leak-guard.sh`) checks the tree and the history against *your* private terms, kept
  outside the repository in `~/.config/code-atlas-oss/private-terms.txt`.
- **No new network exposure**: everything listens on `127.0.0.1`; any change to authentication,
  CORS, the `Host` check or the policy gates comes with tests showing what is refused.
- **Never print a secret**, even in tests or error messages.
- **The contract is generated**: change `backend/atlas/schemas.py`, then
  `uv run atlas openapi --output ../contract/openapi.yaml` and `npm run contract` in `web/`.
- Commit messages: imperative mood, say what changes for the user.
