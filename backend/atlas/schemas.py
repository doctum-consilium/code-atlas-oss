"""Shapes exchanged with the fronts. They produce ``contract/openapi.yaml``, the source of the
TypeScript client and of the Dart contract test: changing a field here changes the contract, and
the CI checks it."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QUESTION_MAX = 4000


class Strict(BaseModel):
    """Unknown fields are refused: a typo in a front shows up at once."""

    model_config = ConfigDict(extra="forbid")


class Filters(Strict):
    """Search filters; an empty list does not filter."""

    repos: list[str] = Field(default_factory=list, max_length=200)
    languages: list[str] = Field(default_factory=list, max_length=50)
    types: list[Literal["code", "test", "doc", "config"]] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list, max_length=50)


class SearchRequest(Strict):
    """Search without a chat model."""

    question: str = Field(min_length=1, max_length=QUESTION_MAX)
    filters: Filters = Field(default_factory=Filters)
    k: int = Field(default=10, ge=1, le=30)
    mode: Literal["hybrid", "lexical", "vector"] = "hybrid"


class ChunkOut(BaseModel):
    """A chunk found."""

    id: int
    repo: str
    path: str
    language: str
    type: str
    kind: str
    symbol: str | None
    line_start: int
    line_end: int
    text: str
    url: str | None
    score: float
    local_only: bool
    ranks: dict[str, int] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Search result."""

    results: list[ChunkOut]
    duration_ms: int


class QuestionRequest(Strict):
    """Question to the chatbot."""

    question: str = Field(min_length=1, max_length=QUESTION_MAX)
    conversation_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    mode: Literal["local", "gateway"] = "local"
    model: str | None = Field(default=None, max_length=100)
    filters: Filters = Field(default_factory=Filters)


class RepoOut(BaseModel):
    """An indexed repository."""

    key: str
    commit: str
    files: int
    chunks: int
    indexed_at: str
    local_only: bool


class Facets(BaseModel):
    """Available filter values."""

    repos: list[str]
    languages: list[str]
    types: list[str]
    owners: list[str]


class FileOut(BaseModel):
    """Content of an indexed file (lines holding secrets already masked)."""

    repo: str
    path: str
    language: str
    content: str
    masked_lines: list[int]
    url: str | None


class LocalModel(BaseModel):
    """A model of the local server."""

    name: str
    installed: bool
    default: bool


class RemoteModel(BaseModel):
    """A gateway model and its policy verdict."""

    alias: str
    provider: str
    allowed: bool
    reason: str
    verified_on: str
    source: str
    warning: str | None = None


class Models(BaseModel):
    """Models offered on screen."""

    local: list[LocalModel]
    gateway: list[RemoteModel]
    gateway_enabled: bool


class IndexStatus(BaseModel):
    """State of the index update."""

    running: bool
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None


class Me(BaseModel):
    """Identity seen by the API."""

    subject: str
    email: str
    client: str
    admin: bool


class ConversationSummary(BaseModel):
    """A conversation in the history."""

    id: str
    title: str
    created_at: str


class Citation(BaseModel):
    """A chunk cited by an answer."""

    n: int
    chunk_id: int
    repo: str
    path: str
    line_start: int
    line_end: int
    url: str | None


class Message(BaseModel):
    """A message of a conversation."""

    role: Literal["user", "assistant"]
    content: str
    model: str | None
    citations: list[Citation]
    created_at: str


class Conversation(BaseModel):
    """A full conversation."""

    id: str
    title: str
    created_at: str
    messages: list[Message]


class OidcPublic(BaseModel):
    """What a front needs to start an OIDC login (all public values)."""

    issuer: str
    web_client: str
    desktop_client: str


class PublicConfig(BaseModel):
    """Served without a token: how the fronts should sign in, and in which language."""

    auth_mode: Literal["token", "oidc"]
    language: Literal["en", "fr"]
    oidc: OidcPublic | None = None


class Health(BaseModel):
    """Probe answer."""

    status: Literal["ok"]
