"""Require an authenticator code for admins, and set up the erasure service client (ADR 0032).

Idempotent; safe to re-run. Talks to the Keycloak admin REST API with the
master-realm admin credentials read from root-only env files, and never prints
a credential. Steps:

1. realm role ``mfa_required``, included in ``org_admin`` and ``superadmin``;
2. TOTP policy (6 digits, 30 s);
3. browser flow ``radbrain browser`` = a copy of the built-in ``browser`` flow in
   which the generic "user has OTP configured" subflow skips ``mfa_required``
   users, plus a ``radbrain admin otp`` subflow that always asks them for a
   code (an admin without an authenticator is sent to enrol one first);
4. that flow bound as the realm's browser flow;
5. with ``--ops-secret-file``: the confidential client ``radbrain-ops`` whose
   service account holds only ``realm-management/manage-users``, used by the
   account-erasure job to revoke the erased user's sessions.

``--check`` reports the state without changing anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

REALM = "radbrain"
FLOW = "radbrain browser"
ADMIN_SUBFLOW = "radbrain admin otp"
ROLE = "mfa_required"
ADMIN_ROLES = ("org_admin", "superadmin")
OPS_CLIENT = "radbrain-ops"
OTP_POLICY = {"otpPolicyType": "totp", "otpPolicyAlgorithm": "HmacSHA1", "otpPolicyDigits": 6,
              "otpPolicyPeriod": 30, "otpPolicyLookAheadWindow": 1}


def read_env(*paths: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    if "=" in line and not line.lstrip().startswith("#"):
                        key, value = line.strip().split("=", 1)
                        values[key] = value
        except FileNotFoundError:
            continue
    return values


class Admin:
    def __init__(self, base: str, user: str, password: str) -> None:
        self.base = base.rstrip("/")
        form = urllib.parse.urlencode({"grant_type": "password", "client_id": "admin-cli",
                                       "username": user, "password": password}).encode()
        token = self._send("POST", "/realms/master/protocol/openid-connect/token", form,
                           "application/x-www-form-urlencoded")
        self.token = str(token["access_token"])

    def _send(self, method: str, path: str, body: bytes | None, ctype: str,
              auth: bool = False) -> Any:
        request = urllib.request.Request(self.base + path, data=body, method=method)
        request.add_header("Content-Type", ctype)
        if auth:
            request.add_header("Authorization", f"Bearer {self.token}")
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310 - fixed admin URL
            raw = response.read()
        return json.loads(raw) if raw else None

    def call(self, method: str, path: str, payload: Any = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        return self._send(method, f"/admin/realms/{REALM}{path}", body, "application/json", True)

    def maybe(self, path: str) -> Any:
        try:
            return self.call("GET", path)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise


def q(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def ensure_role(admin: Admin) -> None:
    role = admin.maybe(f"/roles/{ROLE}")
    if role is None:
        admin.call("POST", "/roles", {"name": ROLE, "description":
                   "Must pass an authenticator code at sign-in (ADR 0032)."})
        role = admin.call("GET", f"/roles/{ROLE}")
    for name in ADMIN_ROLES:
        composites = admin.call("GET", f"/roles/{name}/composites") or []
        if not any(c.get("name") == ROLE for c in composites):
            admin.call("POST", f"/roles/{name}/composites", [role])
    print(f"  role {ROLE} present and included in {', '.join(ADMIN_ROLES)}")


def executions(admin: Admin, flow: str) -> list[dict[str, Any]]:
    return list(admin.call("GET", f"/authentication/flows/{q(flow)}/executions") or [])


def set_requirement(admin: Admin, flow: str, execution: dict[str, Any], value: str) -> None:
    if execution.get("requirement") != value:
        admin.call("PUT", f"/authentication/flows/{q(flow)}/executions",
                   {**execution, "requirement": value})


def ensure_condition(admin: Admin, subflow: str, alias: str, negate: bool) -> None:
    """A REQUIRED ``conditional-user-role`` on ``mfa_required`` inside ``subflow``."""
    provider = "conditional-user-role"
    found = [e for e in executions(admin, subflow) if e.get("providerId") == provider]
    if not found:
        admin.call("POST", f"/authentication/flows/{q(subflow)}/executions/execution",
                   {"provider": provider})
        found = [e for e in executions(admin, subflow) if e.get("providerId") == provider]
    execution = found[0]
    set_requirement(admin, subflow, execution, "REQUIRED")
    if not execution.get("authenticationConfig"):
        admin.call("POST", f"/authentication/executions/{execution['id']}/config",
                   {"alias": alias, "config": {"condUserRole": ROLE,
                                               "negate": "true" if negate else "false"}})


def ensure_execution(admin: Admin, subflow: str, provider: str) -> None:
    found = [e for e in executions(admin, subflow) if e.get("providerId") == provider]
    if not found:
        admin.call("POST", f"/authentication/flows/{q(subflow)}/executions/execution",
                   {"provider": provider})
        found = [e for e in executions(admin, subflow) if e.get("providerId") == provider]
    set_requirement(admin, subflow, found[0], "REQUIRED")


def forms_subflows(admin: Admin) -> tuple[str, str]:
    """(forms subflow, generic conditional-OTP subflow) of the copied flow."""
    rows = executions(admin, FLOW)
    forms = next(e["displayName"] for e in rows
                 if e.get("authenticationFlow") and e.get("level") == 0
                 and "forms" in e["displayName"].lower())
    generic = next(e["displayName"] for e in rows
                   if e.get("authenticationFlow") and e.get("level") == 1
                   and "conditional otp" in e["displayName"].lower())
    return forms, generic


def ensure_flow(admin: Admin) -> None:
    flows = admin.call("GET", "/authentication/flows") or []
    if not any(f.get("alias") == FLOW for f in flows):
        admin.call("POST", "/authentication/flows/browser/copy", {"newName": FLOW})
    forms, generic = forms_subflows(admin)
    ensure_condition(admin, generic, "radbrain-otp-skip-mfa-role", negate=True)
    if not any(e.get("displayName") == ADMIN_SUBFLOW for e in executions(admin, forms)):
        admin.call("POST", f"/authentication/flows/{q(forms)}/executions/flow",
                   {"alias": ADMIN_SUBFLOW, "type": "basic-flow",
                    "provider": "registration-page-form",
                    "description": "Authenticator code for mfa_required users (ADR 0032)"})
    sub = next(e for e in executions(admin, forms) if e.get("displayName") == ADMIN_SUBFLOW)
    set_requirement(admin, forms, sub, "CONDITIONAL")
    ensure_condition(admin, ADMIN_SUBFLOW, "radbrain-otp-mfa-role", negate=False)
    ensure_execution(admin, ADMIN_SUBFLOW, "auth-otp-form")
    realm = admin.call("GET", "")
    if realm.get("browserFlow") != FLOW or any(realm.get(k) != v for k, v in OTP_POLICY.items()):
        admin.call("PUT", "", {"browserFlow": FLOW, **OTP_POLICY})
    print(f"  browser flow '{FLOW}' bound; admins need an authenticator code")


def ensure_ops_client(admin: Admin, secret: str) -> None:
    found = admin.call("GET", f"/clients?clientId={q(OPS_CLIENT)}") or []
    spec = {"clientId": OPS_CLIENT, "enabled": True, "publicClient": False,
            "serviceAccountsEnabled": True, "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False, "implicitFlowEnabled": False,
            "fullScopeAllowed": False, "secret": secret}
    if found:
        admin.call("PUT", f"/clients/{found[0]['id']}", {**found[0], **spec})
    else:
        admin.call("POST", "/clients", spec)
        found = admin.call("GET", f"/clients?clientId={q(OPS_CLIENT)}")
    account = admin.call("GET", f"/clients/{found[0]['id']}/service-account-user")
    management = admin.call("GET", "/clients?clientId=realm-management")[0]
    role = admin.call("GET", f"/clients/{management['id']}/roles/manage-users")
    admin.call("POST", f"/users/{account['id']}/role-mappings/clients/{management['id']}",
               [role])
    print(f"  client {OPS_CLIENT}: service account with manage-users only (secret not shown)")


def check(admin: Admin) -> int:
    realm = admin.call("GET", "")
    role = admin.maybe(f"/roles/{ROLE}")
    ops = admin.call("GET", f"/clients?clientId={q(OPS_CLIENT)}") or []
    print(f"  browserFlow={realm.get('browserFlow')} otpDigits={realm.get('otpPolicyDigits')}")
    print(f"  role {ROLE}: {'present' if role else 'missing'}; ops client: "
          f"{'present' if ops else 'missing'}")
    return 0 if realm.get("browserFlow") == FLOW and role else 1


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://keycloak:8080")
    parser.add_argument("--env", nargs="+", required=True,
                        help="env files holding KEYCLOAK_ADMIN_USER / KEYCLOAK_ADMIN_PASSWORD")
    parser.add_argument("--ops-secret-file", help="env file holding RADBRAIN_OPS_CLIENT_SECRET")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    env = read_env(*args.env)
    admin = Admin(args.base, env["KEYCLOAK_ADMIN_USER"], env["KEYCLOAK_ADMIN_PASSWORD"])
    if args.check:
        return check(admin)
    ensure_role(admin)
    ensure_flow(admin)
    if args.ops_secret_file:
        secret = read_env(args.ops_secret_file).get("RADBRAIN_OPS_CLIENT_SECRET", "")
        if len(secret) < 32:
            print("ops client secret missing or shorter than 32 characters", file=sys.stderr)
            return 2
        ensure_ops_client(admin, secret)
    return check(admin)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
