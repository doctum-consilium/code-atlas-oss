"""The API's front door. Two modes, chosen in ``[auth] mode``.

``token`` (default, one user on this machine)
    A random 256-bit token lives in a 0600 file. A request opens the API only with
    ``Authorization: Bearer <that token>``, compared in constant time.

``oidc`` (any OpenID Connect provider)
    An access token opens the API only if ALL of these hold:

    - signed by a key of the issuer (RS256/ES256/PS256, never ``none`` nor HMAC), not expired;
    - issued by the configured issuer (``iss``) for the API (``aud`` contains the audience);
    - requested by an accepted client (``azp``), if a client list is set;
    - an access token, not an ID token (``typ``), if ``token_type`` is set;
    - carrying the user role at ``roles_claim``, if a role is set;
    - with a verified e-mail from the allowed list, if a list is set.

    The public keys (JWKS) are cached 10 minutes and re-read when an unknown ``kid`` arrives. If
    the provider is down, the known keys still work; with no key at all, everything is refused.

A token is never logged.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import jwt

from atlas.config import AuthSettings, OidcSettings, read_secret

log = logging.getLogger("atlas.auth")

ALGORITHMS = ("RS256", "ES256", "PS256")
JWKS_SECONDS = 600
MIN_REREAD_SECONDS = 30


class Rejected(Exception):
    """Access refused; ``status`` is 401 (not identified) or 403 (identified, not allowed).

    ``reason`` goes to the log, never to the caller.
    """

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class Identity:
    """Who is calling."""

    subject: str
    email: str
    client: str
    admin: bool
    auth_time: int | None


class Verifier(Protocol):
    """Turns an ``Authorization`` header into an :class:`Identity`."""

    def verify(self, header: str | None) -> Identity:
        """Identity, or :class:`Rejected`."""
        ...

    def require_admin(self, identity: Identity, now: float | None = None) -> None:
        """Admin role and recent login, or :class:`Rejected` (403)."""
        ...


def _bearer(header: str | None) -> str:
    if not header or not header.startswith("Bearer "):
        raise Rejected(401, "no Bearer header")
    return header[7:].strip()


def create_token_file(path: Path) -> bool:
    """Create the API token (0600) if missing; True if created. Never prints it."""
    if path.is_file() and path.read_text(encoding="utf-8").strip():
        return False
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(secrets.token_urlsafe(32) + "\n")
    return True


class TokenVerifier:
    """``token`` mode: one secret shared by the user's own fronts, on this machine."""

    def __init__(self, token_file: str) -> None:
        self.token_file = token_file

    def verify(self, header: str | None) -> Identity:
        """Constant-time comparison with the token file."""
        presented = _bearer(header)
        expected = read_secret(self.token_file)
        if not expected:
            raise Rejected(401, "no API token file")
        if not hmac.compare_digest(presented.encode(), expected.encode()):
            raise Rejected(401, "wrong API token")
        return Identity("local", "", "token", admin=True, auth_time=int(time.time()))

    def require_admin(self, identity: Identity, now: float | None = None) -> None:
        """The token holder is the machine's owner: always admin."""
        if not identity.admin:
            raise Rejected(403, "admin role missing")


JwksReader = Callable[[str], dict[str, Any]]


def read_jwks(url: str) -> dict[str, Any]:
    """Download the issuer's JWKS."""
    response = httpx.get(url, timeout=5.0)
    response.raise_for_status()
    data: dict[str, Any] = response.json()
    return data


def discover_jwks_url(issuer: str) -> str:
    """JWKS URL from the issuer's discovery document (Keycloak path as a fallback)."""
    try:
        response = httpx.get(f"{issuer.rstrip('/')}/.well-known/openid-configuration", timeout=5.0)
        response.raise_for_status()
        return str(response.json()["jwks_uri"])
    except (httpx.HTTPError, ValueError, KeyError):
        return f"{issuer.rstrip('/')}/protocol/openid-connect/certs"


def claim(claims: dict[str, Any], dotted: str) -> Any:
    """Value at a dotted path (``resource_access.code-atlas.roles``), or ``None``."""
    value: Any = claims
    for part in dotted.split(".") if dotted else []:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


class OidcVerifier:
    """``oidc`` mode; thread-safe."""

    def __init__(
        self,
        settings: OidcSettings,
        reader: JwksReader = read_jwks,
        jwks_url: str | None = None,
    ) -> None:
        self.s = settings
        self._reader = reader
        self._jwks_url = jwks_url
        self._keys: dict[str, Any] = {}
        self._read_at = 0.0
        self._tried_at = 0.0
        self._lock = threading.Lock()

    def _url(self) -> str:
        if self._jwks_url is None:
            self._jwks_url = discover_jwks_url(self.s.issuer)
        return self._jwks_url

    def _reread(self, force: bool) -> None:
        now = time.monotonic()
        with self._lock:
            fresh = now - self._read_at < JWKS_SECONDS
            recent = now - self._tried_at < MIN_REREAD_SECONDS
            if (fresh and not force) or recent:
                return
            self._tried_at = now
            try:
                jwks = self._reader(self._url())
            except Exception as error:  # noqa: BLE001 -- provider down: keep the known keys
                log.warning(
                    "JWKS unreadable (%s); known keys: %d", type(error).__name__, len(self._keys)
                )
                return
            keys = {}
            for jwk in jwks.get("keys", []):
                if jwk.get("use", "sig") != "sig" or jwk.get("alg") not in ALGORITHMS:
                    continue
                try:
                    keys[jwk["kid"]] = jwt.PyJWK(jwk).key
                except (jwt.PyJWTError, KeyError, ValueError):
                    continue  # one malformed key does not invalidate the others
            if keys:
                self._keys, self._read_at = keys, now

    def _key(self, kid: str | None) -> Any:
        self._reread(force=False)
        if kid not in self._keys:
            self._reread(force=True)
        if kid not in self._keys:
            raise Rejected(401, "unknown signing key")
        return self._keys[kid]

    def verify(self, header: str | None) -> Identity:
        """Identity carried by the ``Authorization`` header; raises :class:`Rejected`."""
        token = _bearer(header)
        try:
            head = jwt.get_unverified_header(token)
        except jwt.PyJWTError as error:
            raise Rejected(401, "unreadable token") from error
        if head.get("alg") not in ALGORITHMS:
            raise Rejected(401, f"algorithm refused: {head.get('alg')}")
        key = self._key(head.get("kid"))
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key,
                algorithms=list(ALGORITHMS),
                audience=self.s.audience,
                issuer=self.s.issuer,
                leeway=self.s.leeway_s,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise Rejected(401, "token expired") from error
        except jwt.PyJWTError as error:
            raise Rejected(401, f"invalid token ({type(error).__name__})") from error
        return self._authorise(claims)

    def _roles(self, claims: dict[str, Any]) -> list[str]:
        value = claim(claims, self.s.roles_claim)
        if isinstance(value, str):
            return [value]
        return [str(v) for v in value] if isinstance(value, list) else []

    def _authorise(self, c: dict[str, Any]) -> Identity:
        if self.s.token_type and c.get("typ") != self.s.token_type:
            raise Rejected(401, f"token type refused: {c.get('typ')}")
        client = str(c.get("azp", ""))
        if self.s.clients and client not in self.s.clients:
            raise Rejected(403, f"client refused: {client}")
        roles = self._roles(c)
        if self.s.user_role and self.s.user_role not in roles:
            raise Rejected(403, "user role missing")
        email = str(c.get("email", "")).lower()
        if self.s.require_email_verified and self.s.allowed_emails and not c.get("email_verified"):
            raise Rejected(403, "e-mail not verified")
        if self.s.allowed_emails and email not in {e.lower() for e in self.s.allowed_emails}:
            raise Rejected(403, "e-mail not allowed")
        auth_time = c.get("auth_time")
        return Identity(
            subject=str(c["sub"]),
            email=email,
            client=client,
            admin=bool(self.s.admin_role) and self.s.admin_role in roles,
            auth_time=int(auth_time) if isinstance(auth_time, int | float) else None,
        )

    def require_admin(self, identity: Identity, now: float | None = None) -> None:
        """Admin role AND a login younger than ``admin_max_auth_age_s``."""
        if not identity.admin:
            raise Rejected(403, "admin role missing")
        instant = time.time() if now is None else now
        if identity.auth_time is None or instant - identity.auth_time > self.s.admin_max_auth_age_s:
            raise Rejected(403, "login too old for an admin action")


def verifier_for(settings: AuthSettings) -> Verifier:
    """The verifier matching ``[auth] mode``."""
    if settings.mode == "token":
        return TokenVerifier(settings.token_file)
    if settings.mode == "oidc":
        if not settings.oidc.issuer:
            raise SystemExit("[auth.oidc] issuer is required in oidc mode")
        return OidcVerifier(settings.oidc)
    raise SystemExit(f"Unknown [auth] mode: {settings.mode!r} (token or oidc)")
