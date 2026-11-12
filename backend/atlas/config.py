"""Settings, read from one TOML file.

Lookup order: ``$CODE_ATLAS_CONFIG``, then ``~/.config/code-atlas/config.toml``. The repository
only ships ``config/config.example.toml``. Secrets never live in this file: it only names the
files (mode 0600) that hold them, read at the last moment and never logged.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path("~/.config/code-atlas/config.toml")


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _tuples(section: dict[str, Any]) -> Any:
    """TOML lists become tuples (settings are immutable)."""
    return {k: tuple(v) if isinstance(v, list) else v for k, v in section.items()}


def read_secret(path: str) -> str | None:
    """Content of a secret file, stripped, or ``None`` if the file does not exist."""
    target = _path(path)
    return target.read_text(encoding="utf-8").strip() if target.is_file() else None


@dataclass(frozen=True)
class OidcSettings:
    """What an OIDC access token must carry to open the API."""

    issuer: str = ""
    audience: str = "code-atlas"
    clients: tuple[str, ...] = ()  # allowed ``azp`` values; empty = any client
    web_client: str = "code-atlas-web"
    desktop_client: str = "code-atlas-desktop"
    roles_claim: str = "resource_access.code-atlas.roles"  # dotted path in the token
    user_role: str = "user"  # empty = no role required
    admin_role: str = "admin"
    allowed_emails: tuple[str, ...] = ()  # empty = any user with the role
    require_email_verified: bool = True
    token_type: str = "Bearer"  # Keycloak's ``typ`` claim; empty to skip the check
    admin_max_auth_age_s: int = 600
    leeway_s: int = 30


@dataclass(frozen=True)
class AuthSettings:
    """``token``: one random token stored in a 0600 file (single user, this machine).
    ``oidc``: access tokens from any OpenID Connect provider (Keycloak, Authentik, Auth0…)."""

    mode: str = "token"
    token_file: str = "~/.config/code-atlas/api-token"
    oidc: OidcSettings = field(default_factory=OidcSettings)


@dataclass(frozen=True)
class DatabaseSettings:
    """Local PostgreSQL (ParadeDB image: pgvector + pg_search)."""

    host: str = "127.0.0.1"
    port: int = 55432
    user: str = "atlas"
    name: str = "atlas"
    password_file: str = "~/.config/code-atlas/db-password"

    def dsn(self) -> str:
        """Connection string; ``CODE_ATLAS_DSN`` wins (tests, CI). Never print it."""
        if os.environ.get("CODE_ATLAS_DSN"):
            return os.environ["CODE_ATLAS_DSN"]
        password = read_secret(self.password_file) or ""
        return (
            f"host={self.host} port={self.port} user={self.user} dbname={self.name} "
            f"password={password}"
        )


@dataclass(frozen=True)
class CorpusSettings:
    """Which repositories and files get indexed."""

    roots: tuple[Path, ...] = ()
    owners: tuple[str, ...] = ()  # accepted owners (org/user); empty = any repository
    exclude_forks: bool = False  # ask GitHub (gh CLI) and skip forks
    exclude: dict[str, str] = field(default_factory=dict)  # "owner/name" -> reason
    local_only: frozenset[str] = frozenset()  # chunks never sent to a gateway
    max_file_bytes: int = 1_000_000
    links: dict[str, str] = field(
        default_factory=lambda: {
            "github.com": "https://github.com/{repo}/blob/{commit}/{path}#L{start}-L{end}",
            "gitlab.com": "https://gitlab.com/{repo}/-/blob/{commit}/{path}#L{start}-{end}",
        }
    )


@dataclass(frozen=True)
class ModelSettings:
    """Search models (run locally) and chat models."""

    embedder: str = "Qwen/Qwen3-Embedding-0.6B"
    dimension: int = 1024
    query_prompt: str = "query"  # sentence-transformers prompt name for queries; "" = none
    reranker: str = "BAAI/bge-reranker-v2-m3"  # "" disables reranking
    local_url: str = "http://127.0.0.1:11434"
    local_default: str = "qwen2.5-coder:14b"
    local: tuple[str, ...] = ("qwen2.5-coder:14b",)


@dataclass(frozen=True)
class GatewaySettings:
    """Optional OpenAI-compatible gateway. Only models allowed by the policy file are used."""

    enabled: bool = False
    url: str = ""
    key_file: str = "~/.config/code-atlas/gateway-key"
    policy_file: str = "~/.config/code-atlas/policy.toml"

    def key(self) -> str | None:
        """Gateway key (``CODE_ATLAS_GATEWAY_KEY`` wins), or ``None``."""
        return os.environ.get("CODE_ATLAS_GATEWAY_KEY") or read_secret(self.key_file)


@dataclass(frozen=True)
class LimitSettings:
    """Rate and size limits."""

    searches_per_minute: int = 60
    questions_per_minute: int = 10
    question_max_chars: int = 4000


@dataclass(frozen=True)
class ThermalSettings:
    """Pause heavy work when the machine gets hot."""

    enabled: bool = True
    gpu_max_c: float = 80.0
    cpu_max_c: float = 88.0


@dataclass(frozen=True)
class Settings:
    """All settings."""

    language: str = "en"
    host: str = "127.0.0.1"
    port: int = 8790
    web_origins: tuple[str, ...] = ("http://127.0.0.1:4173", "http://127.0.0.1:5173")
    auth: AuthSettings = field(default_factory=AuthSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    corpus: CorpusSettings = field(default_factory=CorpusSettings)
    models: ModelSettings = field(default_factory=ModelSettings)
    gateway: GatewaySettings = field(default_factory=GatewaySettings)
    limits: LimitSettings = field(default_factory=LimitSettings)
    thermal: ThermalSettings = field(default_factory=ThermalSettings)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        """Read the settings file (see module docstring for the lookup order)."""
        target = path or _path(os.environ.get("CODE_ATLAS_CONFIG", str(DEFAULT_CONFIG)))
        if not target.is_file():
            raise SystemExit(
                f"No settings file at {target}. Copy config/config.example.toml there "
                "(or run scripts/install.sh)."
            )
        return cls.from_dict(tomllib.loads(target.read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        """Build settings from parsed TOML; unknown keys are an error (typos show up early)."""
        server = raw.get("server", {})
        auth = dict(raw.get("auth", {}))
        oidc = auth.pop("oidc", {})
        corpus = dict(raw.get("corpus", {}))
        models = raw.get("models", {})
        return cls(
            language=raw.get("language", "en"),
            host=server.get("host", "127.0.0.1"),
            port=int(server.get("port", 8790)),
            web_origins=tuple(server.get("web_origins", cls.web_origins)),
            auth=AuthSettings(
                **auth,
                oidc=OidcSettings(**_tuples(oidc)),
            ),
            database=DatabaseSettings(**raw.get("database", {})),
            corpus=CorpusSettings(
                roots=tuple(_path(r) for r in corpus.pop("roots", [])),
                owners=tuple(corpus.pop("owners", [])),
                local_only=frozenset(corpus.pop("local_only", [])),
                exclude=dict(corpus.pop("exclude", {})),
                links={**CorpusSettings().links, **corpus.pop("links", {})},
                **corpus,
            ),
            models=ModelSettings(**_tuples(models)),
            gateway=GatewaySettings(**raw.get("gateway", {})),
            limits=LimitSettings(**raw.get("limits", {})),
            thermal=ThermalSettings(**raw.get("thermal", {})),
        )
