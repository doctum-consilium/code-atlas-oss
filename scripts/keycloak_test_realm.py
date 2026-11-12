#!/usr/bin/env python3
"""Prepare a TEST Keycloak (local or CI): realm and test account, then the code-atlas clients.

    KC_ADMIN=admin KC_ADMIN_PASSWORD=… KC_TEST_PASSWORD=… \\
        python3 scripts/keycloak_test_realm.py --url http://127.0.0.1:8180

Only for a throwaway Keycloak started for tests (``start-dev``): MFA is off and the test account
is ``e2e`` / ``e2e@example.org``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from keycloak_setup import admin_token, clients, grant_roles, request, sync_client

REALM = "test"
EMAIL = "e2e@example.org"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8180")
    args = p.parse_args()
    if not args.url.startswith(("http://127.0.0.1", "http://localhost")):
        raise SystemExit("Test realms only on a local Keycloak.")
    url = args.url.rstrip("/")
    token = admin_token(url)
    if REALM not in {r["realm"] for r in request("GET", f"{url}/admin/realms", token=token)}:
        request(
            "POST",
            f"{url}/admin/realms",
            token=token,
            body={"realm": REALM, "enabled": True, "bruteForceProtected": True},
        )
    base = f"{url}/admin/realms/{REALM}"
    if not request("GET", f"{base}/users?email={EMAIL}&exact=true", token=token):
        request(
            "POST",
            f"{base}/users",
            token=token,
            body={
                "username": "e2e",
                "email": EMAIL,
                "emailVerified": True,
                "enabled": True,
                "firstName": "Test",
                "lastName": "User",
                "credentials": [
                    {
                        "type": "password",
                        "value": os.environ["KC_TEST_PASSWORD"],
                        "temporary": False,
                    }
                ],
            },
        )
    ids = [
        sync_client(url, REALM, token, c)
        for c in clients(None, ["http://127.0.0.1:4173", "http://127.0.0.1:5173"])
    ]
    grant_roles(url, REALM, token, ids[0], EMAIL)
    print(f"Test realm {REALM!r} ready on {url}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
