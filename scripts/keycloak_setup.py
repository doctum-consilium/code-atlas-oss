#!/usr/bin/env python3
"""Create or update the code-atlas clients in a Keycloak realm (``oidc`` mode). Idempotent.

    KC_ADMIN=… KC_ADMIN_PASSWORD=… python3 scripts/keycloak_setup.py \\
        --url https://id.example.com --realm main --email you@example.com

What it sets up:

- ``code-atlas``: a client with no login flow, holding the ``user`` and ``admin`` roles (they
  appear in ``resource_access.code-atlas.roles``, the default ``roles_claim``);
- ``code-atlas-web`` and ``code-atlas-desktop``: PUBLIC clients, PKCE S256 required, no direct
  access grants, no implicit flow. The web client accepts exact redirects to 127.0.0.1:4173 and
  :5173; the desktop accepts ``http://127.0.0.1/*`` (ephemeral loopback port);
- the ``code-atlas`` audience in the access token; 5-minute access tokens, 30-minute idle session,
  12-hour maximum session;
- unless ``--no-mfa``: a dedicated ``code-atlas-browser`` flow requiring password AND a one-time
  code (TOTP), without silently reusing a session opened by another application;
- both roles given to the account with the given e-mail.

Admin credentials come from KC_ADMIN / KC_ADMIN_PASSWORD (never printed, never on the command
line). Use a dedicated admin account and rotate its password afterwards if in doubt.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

AUDIENCE = "code-atlas"
FLOW = "code-atlas-browser"
TIMINGS = {
    "access.token.lifespan": "300",
    "client.session.idle.timeout": "1800",
    "client.session.max.lifespan": "43200",
    "pkce.code.challenge.method": "S256",
}


def request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: Any = None,
    form: dict[str, str] | None = None,
) -> Any:
    """One admin API call; JSON in, JSON out."""
    data, headers = None, {"Accept": "application/json"}
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310 -- admin URL
            text = response.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"Keycloak refused {method} {url.split('?', maxsplit=1)[0]} ({exc.code})."
        ) from None
    return json.loads(text) if text else None


def admin_token(url: str) -> str:
    """Token of the admin account (credentials from the environment, never shown)."""
    try:
        name, password = os.environ["KC_ADMIN"], os.environ["KC_ADMIN_PASSWORD"]
    except KeyError:
        raise SystemExit("Set KC_ADMIN and KC_ADMIN_PASSWORD in the environment.") from None
    r = request(
        "POST",
        f"{url}/realms/master/protocol/openid-connect/token",
        form={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": name,
            "password": password,
        },
    )
    return str(r["access_token"])


def audience_mapper() -> dict[str, Any]:
    return {
        "name": "audience-code-atlas",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.custom.audience": AUDIENCE,
            "access.token.claim": "true",
            "id.token.claim": "false",
        },
    }


def clients(flow_id: str | None, web_origins: list[str]) -> list[dict[str, Any]]:
    """The three clients; ``flow_id`` = imposed login flow (None: the realm's)."""
    # An empty binding is ignored by Keycloak: "" explicitly removes an imposed flow.
    binding = {"browser": flow_id or ""}
    common = {
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": True,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": False,
        "implicitFlowEnabled": False,
        "serviceAccountsEnabled": False,
        "frontchannelLogout": True,
        "fullScopeAllowed": True,
        "authenticationFlowBindingOverrides": binding,
        "protocolMappers": [audience_mapper()],
    }
    return [
        {
            "clientId": AUDIENCE,
            "name": "code-atlas API roles",
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "bearerOnly": True,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "implicitFlowEnabled": False,
            "serviceAccountsEnabled": False,
            "redirectUris": [],
            "webOrigins": [],
            "protocolMappers": [],
        },
        common
        | {
            "clientId": "code-atlas-web",
            "name": "code-atlas web",
            "redirectUris": [f"{o}/signin.html" for o in web_origins],
            "webOrigins": web_origins,
            "attributes": TIMINGS | {"post.logout.redirect.uris": "##".join(web_origins)},
        },
        common
        | {
            "clientId": "code-atlas-desktop",
            "name": "code-atlas desktop",
            "redirectUris": ["http://127.0.0.1/*"],
            "webOrigins": [],
            "attributes": TIMINGS,
        },
    ]


def sync_client(url: str, realm: str, token: str, client: dict[str, Any]) -> str:
    """Create or replace a client; add missing mappers. Returns its internal id."""
    base = f"{url}/admin/realms/{realm}/clients"
    existing = request("GET", f"{base}?clientId={client['clientId']}", token=token)
    if existing:
        internal = str(existing[0]["id"])
        request(
            "PUT",
            f"{base}/{internal}",
            token=token,
            body={k: v for k, v in client.items() if k != "protocolMappers"},
        )
        present = {
            m["name"]
            for m in request("GET", f"{base}/{internal}/protocol-mappers/models", token=token)
        }
        for m in client["protocolMappers"]:
            if m["name"] not in present:
                request("POST", f"{base}/{internal}/protocol-mappers/models", token=token, body=m)
        print(f"Client updated: {client['clientId']}")
    else:
        request("POST", base, token=token, body=client)
        internal = str(
            request("GET", f"{base}?clientId={client['clientId']}", token=token)[0]["id"]
        )
        print(f"Client created: {client['clientId']}")
    return internal


def mfa_flow(url: str, realm: str, token: str) -> str:
    """Copy of the "browser" flow without session reuse (cookie) and with TOTP required."""
    base = f"{url}/admin/realms/{realm}/authentication"
    flows = {f["alias"]: f for f in request("GET", f"{base}/flows", token=token)}
    if FLOW not in flows:
        request("POST", f"{base}/flows/browser/copy", token=token, body={"newName": FLOW})
        flows = {f["alias"]: f for f in request("GET", f"{base}/flows", token=token)}
        print(f"Flow created: {FLOW}")
    executions = request("GET", f"{base}/flows/{urllib.parse.quote(FLOW)}/executions", token=token)
    for e in executions:
        provider, name = e.get("providerId", ""), e.get("displayName", "")
        target = None
        if provider in (
            "auth-cookie",
            "identity-provider-redirector",
            "conditional-user-configured",
        ):
            target = "DISABLED"
        elif (
            provider == "auth-otp-form"
            or (e.get("authenticationFlow") and "OTP" in name)
            or (e.get("authenticationFlow") and e.get("level") == 0 and name.endswith("forms"))
        ):
            target = "REQUIRED"
        if target and e.get("requirement") != target:
            e["requirement"] = target
            request(
                "PUT", f"{base}/flows/{urllib.parse.quote(FLOW)}/executions", token=token, body=e
            )
    return str(flows[FLOW]["id"])


def grant_roles(url: str, realm: str, token: str, roles_client: str, email: str) -> None:
    """``user`` and ``admin`` roles on the ``code-atlas`` client, given to one account."""
    base = f"{url}/admin/realms/{realm}"
    present = {
        r["name"] for r in request("GET", f"{base}/clients/{roles_client}/roles", token=token)
    }
    for name, description in (
        ("user", "opens the code-atlas API"),
        ("admin", "re-indexes, deletes history"),
    ):
        if name not in present:
            request(
                "POST",
                f"{base}/clients/{roles_client}/roles",
                token=token,
                body={"name": name, "description": description},
            )
    accounts = request(
        "GET", f"{base}/users?email={urllib.parse.quote(email)}&exact=true", token=token
    )
    if len(accounts) != 1:
        raise SystemExit(f"{len(accounts)} account(s) with this e-mail in {realm}: no role given.")
    roles = [
        request("GET", f"{base}/clients/{roles_client}/roles/{n}", token=token)
        for n in ("user", "admin")
    ]
    request(
        "POST",
        f"{base}/users/{accounts[0]['id']}/role-mappings/clients/{roles_client}",
        token=token,
        body=roles,
    )
    print("Roles user and admin granted to the given account.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--url", required=True, help="Keycloak base URL, e.g. https://id.example.com")
    p.add_argument("--realm", required=True)
    p.add_argument("--email", required=True, help="account that gets the user and admin roles")
    p.add_argument(
        "--web-origin",
        action="append",
        help="web front origin (repeatable); default 127.0.0.1:4173 and :5173",
    )
    p.add_argument("--no-mfa", action="store_true", help="for a TEST realm only")
    args = p.parse_args()
    url = args.url.rstrip("/")
    origins = args.web_origin or ["http://127.0.0.1:4173", "http://127.0.0.1:5173"]
    token = admin_token(url)
    flow_id = None if args.no_mfa else mfa_flow(url, args.realm, token)
    ids = [sync_client(url, args.realm, token, c) for c in clients(flow_id, origins)]
    grant_roles(url, args.realm, token, ids[0], args.email)
    return 0


if __name__ == "__main__":
    sys.exit(main())
