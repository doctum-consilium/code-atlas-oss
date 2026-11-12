"""Front door: token mode and OIDC mode. Every missing condition refuses; only the right token
passes."""

from __future__ import annotations

import json
import stat
import time
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from atlas import auth
from atlas.auth import OidcVerifier, Rejected, TokenVerifier
from atlas.config import AuthSettings, OidcSettings

ISSUER = "https://id.example.org/realms/main"
SETTINGS = OidcSettings(
    issuer=ISSUER,
    audience="code-atlas",
    clients=("code-atlas-web", "code-atlas-desktop"),
    roles_claim="resource_access.code-atlas.roles",
    user_role="user",
    admin_role="admin",
    allowed_emails=("dev@example.org",),
)

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwks(key: Any = KEY, kid: str = "k1") -> dict[str, Any]:
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {"keys": [public | {"kid": kid, "alg": "RS256", "use": "sig"}]}


def claims(**changes: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": ["code-atlas", "account"],
        "azp": "code-atlas-web",
        "sub": "subject-1",
        "typ": "Bearer",
        "iat": now,
        "exp": now + 300,
        "auth_time": now,
        "email": "Dev@example.org",
        "email_verified": True,
        "resource_access": {"code-atlas": {"roles": ["user"]}},
    }
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}


def token(key: Any = KEY, kid: str = "k1", alg: str = "RS256", **changes: Any) -> str:
    return "Bearer " + jwt.encode(claims(**changes), key, algorithm=alg, headers={"kid": kid})


def verifier(settings: OidcSettings = SETTINGS) -> OidcVerifier:
    return OidcVerifier(settings, lambda _url: jwks(), jwks_url="https://id.example.org/certs")


# ------------------------------------------------------------------ token mode


def test_token_file_created_0600_once(tmp_path: Path) -> None:
    path = tmp_path / "conf" / "api-token"
    assert auth.create_token_file(path) is True
    first = path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and len(first.strip()) >= 40
    assert auth.create_token_file(path) is False and path.read_text() == first


def test_token_mode(tmp_path: Path) -> None:
    path = tmp_path / "api-token"
    auth.create_token_file(path)
    v = TokenVerifier(str(path))
    who = v.verify(f"Bearer {path.read_text().strip()}")
    assert (who.subject, who.admin) == ("local", True)
    v.require_admin(who)
    for header in (None, "Bearer nope", "Basic x"):
        with pytest.raises(Rejected) as error:
            v.verify(header)
        assert error.value.status == 401
    with pytest.raises(Rejected, match="no API token file"):
        TokenVerifier(str(tmp_path / "missing")).verify("Bearer x")


def test_verifier_for_modes(tmp_path: Path) -> None:
    assert isinstance(
        auth.verifier_for(AuthSettings(token_file=str(tmp_path / "t"))), TokenVerifier
    )
    assert isinstance(auth.verifier_for(AuthSettings(mode="oidc", oidc=SETTINGS)), OidcVerifier)
    with pytest.raises(SystemExit, match="issuer"):
        auth.verifier_for(AuthSettings(mode="oidc"))
    with pytest.raises(SystemExit, match="Unknown"):
        auth.verifier_for(AuthSettings(mode="magic"))


# ------------------------------------------------------------------ OIDC mode


def test_the_right_token_passes() -> None:
    who = verifier().verify(token())
    assert (who.subject, who.email, who.client, who.admin) == (
        "subject-1",
        "dev@example.org",
        "code-atlas-web",
        False,
    )


@pytest.mark.parametrize(
    ("changes", "status", "reason"),
    [
        ({"iss": "https://id.example.org/realms/other"}, 401, "InvalidIssuer"),
        ({"aud": "account"}, 401, "InvalidAudience"),
        ({"exp": int(time.time()) - 120}, 401, "expired"),
        ({"typ": "ID"}, 401, "token type"),
        ({"azp": "another-app"}, 403, "client refused"),
        ({"resource_access": {"code-atlas": {"roles": []}}}, 403, "role"),
        ({"email": "intruder@example.org"}, 403, "e-mail not allowed"),
        ({"email_verified": False}, 403, "not verified"),
        ({"sub": None}, 401, "MissingRequiredClaim"),
    ],
)
def test_each_missing_condition_refuses(changes: dict[str, Any], status: int, reason: str) -> None:
    with pytest.raises(Rejected) as error:
        verifier().verify(token(**changes))
    assert error.value.status == status and reason in error.value.reason


def test_relaxed_settings_for_other_providers() -> None:
    relaxed = OidcSettings(
        issuer=ISSUER,
        audience="code-atlas",
        roles_claim="groups",
        user_role="code-atlas",
        token_type="",
        allowed_emails=(),
    )
    who = verifier(relaxed).verify(
        token(azp="anything", typ=None, groups="code-atlas", email_verified=False)
    )
    assert who.subject == "subject-1"
    nobody = OidcSettings(issuer=ISSUER, audience="code-atlas", user_role="", token_type="")
    assert verifier(nobody).verify(token(resource_access=None)).admin is False


def test_bad_signatures_and_algorithms() -> None:
    v = verifier()
    with pytest.raises(Rejected, match="InvalidSignature"):
        v.verify(token(key=OTHER_KEY))
    for alg, key in (("none", None), ("HS256", "shared-secret-of-at-least-32-bytes!")):
        raw = jwt.encode(claims(), key, algorithm=alg, headers={"kid": "k1"})
        with pytest.raises(Rejected, match="algorithm refused"):
            v.verify(f"Bearer {raw}")
    with pytest.raises(Rejected, match="unreadable"):
        v.verify("Bearer not.a.token")


def test_unknown_kid_and_key_rotation() -> None:
    sets = iter([jwks(KEY, "k1"), jwks(OTHER_KEY, "k2")])
    v = OidcVerifier(SETTINGS, lambda _u: next(sets), jwks_url="u")
    v.verify(token())
    v._tried_at = 0.0
    assert v.verify(token(key=OTHER_KEY, kid="k2")).subject == "subject-1"
    with pytest.raises(Rejected, match="unknown signing key"):
        v.verify(token(kid="nope"))


def test_provider_down_keeps_known_keys_and_no_key_refuses_all() -> None:
    state = {"down": False}

    def reader(_url: str) -> dict[str, Any]:
        if state["down"]:
            raise OSError("network down")
        return jwks()

    v = OidcVerifier(SETTINGS, reader, jwks_url="u")
    v.verify(token())
    state["down"] = True
    v._read_at = v._tried_at = 0.0
    assert v.verify(token()).subject == "subject-1"
    with pytest.raises(Rejected, match="unknown signing key"):
        OidcVerifier(SETTINGS, reader, jwks_url="u").verify(token())


def test_jwks_ignores_encryption_and_malformed_keys() -> None:
    enc = jwks(OTHER_KEY, "enc")["keys"][0] | {"use": "enc"}
    broken = {"kid": "x", "alg": "RS256", "kty": "RSA"}
    v = OidcVerifier(SETTINGS, lambda _u: {"keys": [enc, broken, *jwks()["keys"]]}, jwks_url="u")
    assert v.verify(token()).subject == "subject-1"
    assert set(v._keys) == {"k1"}


def test_admin_needs_role_and_recent_login() -> None:
    v = verifier()
    roles = {"code-atlas": {"roles": ["user", "admin"]}}
    admin = v.verify(token(resource_access=roles))
    v.require_admin(admin)
    with pytest.raises(Rejected, match="too old"):
        v.require_admin(admin, now=time.time() + 3600)
    with pytest.raises(Rejected, match="too old"):
        v.require_admin(v.verify(token(resource_access=roles, auth_time=None)))
    with pytest.raises(Rejected, match="admin role missing"):
        v.require_admin(v.verify(token()))


def test_claim_paths() -> None:
    data = {"a": {"b": ["x"]}, "g": "y"}
    assert auth.claim(data, "a.b") == ["x"]
    assert auth.claim(data, "a.c") is None
    assert auth.claim(data, "g.h") is None


def test_jwks_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, timeout: float) -> httpx.Response:
        request = httpx.Request("GET", url)
        if url.endswith("openid-configuration"):
            return httpx.Response(
                200, json={"jwks_uri": "https://id.example.org/jwks"}, request=request
            )
        return httpx.Response(200, json={"keys": []}, request=request)

    monkeypatch.setattr(auth.httpx, "get", fake_get)
    assert auth.discover_jwks_url(ISSUER) == "https://id.example.org/jwks"
    assert auth.read_jwks("https://id.example.org/jwks") == {"keys": []}

    def down(url: str, timeout: float) -> httpx.Response:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(auth.httpx, "get", down)
    assert auth.discover_jwks_url(ISSUER) == f"{ISSUER}/protocol/openid-connect/certs"
