#!/usr/bin/env python3
"""End-to-end OIDC verification against a live Keycloak and the radbrain API.

Runs the browser flow the SvelteKit server performs (PKCE code, login form,
confidential code exchange) and proves the token shape (ADR 0004 audience, opaque
subject), API membership resolution, refusal of forged/missing/spoofed credentials,
role denial (admin routes follow the database role; ``--student-file`` adds a real
student 403), unauthorized tenant-switch refusal, and logout (backchannel logout,
then the refresh token is refused). ADR 0022.

Secrets come from root-only env files and are never printed; neither are token
contents. See .github/workflows/verify-production-oidc.yml for the invocation.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.cookiejar
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from html import unescape as html_unescape
from pathlib import Path
from typing import Any

# The public authorize endpoint sits behind Cloudflare, whose browser integrity
# check refuses the default Python-urllib user agent with 403.
USER_AGENT = "Mozilla/5.0 (compatible; radbrain-verify-oidc/1.0)"
ADMIN_ROLES = {"org_admin", "superadmin"}
ADMIN_ROUTES = ("/v1/admin/ping", "/v1/admin/embedding-usage")


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)

    def ok(self, label: str, condition: bool, detail: str = "") -> bool:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
        if not condition:
            self.failures.append(label)
        return condition


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict[str, str]

    def json(self) -> dict[str, Any]:
        try:
            value = json.loads(self.body)
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def read_env(path: str) -> dict[str, str]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    pairs = [ln.strip().split("=", 1) for ln in lines if "=" in ln and ln.strip()[:1] != "#"]
    return {key: value for key, value in pairs}


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_pkce() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(48))
    return verifier, b64url(hashlib.sha256(verifier.encode()).digest())


def new_opener(jar: http.cookiejar.CookieJar | None = None) -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [NoRedirect()]
    if jar is not None:
        handlers.append(urllib.request.HTTPCookieProcessor(jar))
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


def call(url: str, *, data: dict[str, str] | None = None, headers: dict[str, str] | None = None,
         opener: urllib.request.OpenerDirector | None = None, method: str | None = None,
         ) -> Response:
    """One HTTP(S) request; errors come back as a Response, never raise."""
    if urllib.parse.urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("only http(s) URLs are probed")
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with (opener or new_opener()).open(request, timeout=20) as resp:  # nosec B310
            found = {k.lower(): v for k, v in resp.headers.items()}
            return Response(resp.status, resp.read(), found)
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.read(), {k.lower(): v for k, v in exc.headers.items()})


def check_discovery(report: Report, issuer: str, expected_issuer: str) -> dict[str, Any] | None:
    print("=== 1. the realm publishes the expected endpoints ===")
    try:
        found = call(f"{issuer}/.well-known/openid-configuration")
    except OSError as exc:
        print(f"  [FAIL] discovery unreachable: {type(exc).__name__}")
        return None
    if not report.ok("discovery reachable", found.status == 200, f"HTTP {found.status}"):
        return None
    discovery = found.json()
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri",
                 "end_session_endpoint", "revocation_endpoint"):
        report.ok(f"discovery has {name}", bool(discovery.get(name)))
    found_issuer = str(discovery.get("issuer", ""))
    report.ok("issuer in discovery matches", found_issuer.rstrip("/") == expected_issuer,
              found_issuer)
    methods = discovery.get("code_challenge_methods_supported") or []
    report.ok("PKCE S256 advertised", "S256" in methods)
    return discovery


def _authorize(
    report: Report, discovery: dict[str, Any], client_id: str, redirect_uri: str
) -> tuple[urllib.request.OpenerDirector, str, str, str] | None:
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    opener = new_opener(http.cookiejar.CookieJar())
    query = urllib.parse.urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
        "scope": "openid profile email", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    page = call(f"{discovery['authorization_endpoint']}?{query}", opener=opener)
    report.ok("authorize serves the login page", page.status in {200, 302},
              f"HTTP {page.status}")
    html = page.body.decode("utf-8", "replace")
    if not report.ok("login form served", "kc-form-login" in html):
        return None
    return opener, verifier, state, html


def _submit_login(
    report: Report, issuer: str, opener: urllib.request.OpenerDirector,
    html: str, credentials: tuple[str, str], state: str,
) -> str | None:
    # Use the form's own action URL and hidden fields; Keycloak puts the real
    # action, and any credential id, in the served HTML.
    action = _form_action(html)
    if not report.ok("login form action readable", bool(action)):
        return None
    if action.startswith("/"):
        action = f"{issuer}{action}"
    fields = _hidden_fields(html)
    fields.update({"username": credentials[0], "password": credentials[1]})
    posted = call(action, data=fields, opener=opener)
    location = posted.headers.get("location", "")
    if not report.ok("login accepted", bool(location), f"HTTP {posted.status}"):
        return None
    # Only the path is printed; the query carries the authorization code.
    target = urllib.parse.urlparse(location)
    print(f"         redirected to {target.scheme}://{target.netloc}{target.path}")
    params = dict(urllib.parse.parse_qsl(target.query))
    if not report.ok("no provider error", "error" not in params, params.get("error", "")):
        return None
    report.ok("state echoed back unchanged", params.get("state") == state)
    code = params.get("code")
    return code if report.ok("authorization code issued", bool(code)) else None


def login(
    report: Report, args: argparse.Namespace, discovery: dict[str, Any],
    client_secret: str, credentials: tuple[str, str],
) -> dict[str, Any] | None:
    issuer = args.issuer.rstrip("/")
    started = _authorize(report, discovery, args.client_id, args.redirect_uri)
    if started is None:
        return None
    opener, verifier, state, html = started
    code = _submit_login(report, issuer, opener, html, credentials, state)
    if code is None:
        return None
    exchanged = call(discovery["token_endpoint"], data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": args.redirect_uri, "client_id": args.client_id,
        "client_secret": client_secret, "code_verifier": verifier,
    })
    # Only the OAuth error code is shown; it contains no secrets.
    if not report.ok("token exchange succeeded", exchanged.status == 200,
                     f"HTTP {exchanged.status} {exchanged.json().get('error', '')}".strip()):
        return None
    tokens = exchanged.json()
    for name in ("access_token", "refresh_token", "id_token"):
        report.ok(f"{name.replace('_', ' ')} issued", bool(tokens.get(name)))
    return tokens


def check_claims(report: Report, access: str, expected_issuer: str, username: str) -> None:
    print("\n=== 4. access token structure (claims are not printed) ===")
    claims = _decode_claims(access)
    report.ok("issuer claim matches the realm",
              str(claims.get("iss", "")).rstrip("/") == expected_issuer)
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    report.ok("audience includes radbrain-api (ADR 0004)", "radbrain-api" in audiences,
              f"aud={sorted(str(a) for a in audiences if a)}")
    subject = claims.get("sub", "")
    report.ok("subject present and opaque", bool(subject) and subject != username)
    report.ok("token is short-lived", _lifetime_seconds(claims) <= 1800)
    # Roles are deliberately NOT taken from the token: membership and role come
    # from the database after signature and audience verification.
    access_claim = claims.get("realm_access")
    roles = access_claim.get("roles") if isinstance(access_claim, dict) else None
    print(f"  [INFO] token role claims present: {bool(roles)} "
          "(authorisation comes from the database regardless)")


def check_api(report: Report, api: str, access: str) -> dict[str, Any]:
    print("\n=== 5. the API accepts the token and resolves a membership ===")
    me = call(f"{api}/v1/me", headers={"Authorization": f"Bearer {access}"})
    report.ok("authenticated identity lookup succeeded", me.status == 200, f"HTTP {me.status}")
    identity = me.json()
    print(f"         role={identity.get('role')} tenant_present={bool(identity.get('id'))}")
    print("\n=== 6. forged, missing and spoofed credentials are refused ===")
    tampered = access[:-4] + ("bbbb" if access.endswith("aaaa") else "aaaa")
    spoof = {"X-User-Id": str(uuid.uuid4()), "X-Tenant-Id": str(uuid.uuid4()),
             "X-Role": "superadmin"}
    probes: tuple[tuple[str, str, dict[str, str]], ...] = (
        ("tampered signature refused", "/v1/me", {"Authorization": f"Bearer {tampered}"}),
        ("missing token refused", "/v1/me", {}),
        ("dev identity headers refused on an admin route", "/v1/admin/embedding-usage", spoof),
        ("forged web assertion refused on an admin route", "/v1/admin/embedding-usage",
         {**spoof, "X-Radbrain-Assertion": "forged.assertion.value"}),
        ("tampered token refused on an admin route", "/v1/admin/embedding-usage",
         {"Authorization": f"Bearer {tampered}"}),
    )
    for label, path, headers in probes:
        status = call(f"{api}{path}", headers=headers).status
        report.ok(label, status in {401, 403}, f"HTTP {status}")
    return identity


def check_roles(report: Report, api: str, access: str, role: str, student: str | None) -> None:
    print("\n=== 7. role denial comes from the database membership ===")
    bearer = {"Authorization": f"Bearer {access}"}
    admin = role in ADMIN_ROLES
    for path in ADMIN_ROUTES:
        status = call(f"{api}{path}", headers=bearer).status
        # embedding-usage answers 404 when embeddings are not configured.
        allowed = status in {200, 404} if admin else status == 403
        report.ok(f"{path} for role {role!r}", allowed, f"HTTP {status}")
    if student is None:
        print("  [INFO] no --student-file; a student principal was not exercised "
              "(covered by API unit tests)")
        return
    for path in ADMIN_ROUTES:
        status = call(f"{api}{path}", headers={"Authorization": f"Bearer {student}"}).status
        report.ok(f"student gets 403 on {path}", status == 403, f"HTTP {status}")


def check_tenant_switch(report: Report, api: str, access: str, own_tenant: str) -> None:
    print("\n=== 8. tenant switch is limited to the caller's memberships ===")
    bearer = {"Authorization": f"Bearer {access}"}
    foreign = call(f"{api}/v1/tenants/switch?tenant_id={uuid.uuid4()}", headers=bearer,
                   method="POST")
    report.ok("switch to a foreign tenant refused", foreign.status == 403,
              f"HTTP {foreign.status}")
    if own_tenant:
        own = call(f"{api}/v1/tenants/switch?tenant_id={own_tenant}", headers=bearer,
                   method="POST")
        report.ok("switch to the caller's own tenant allowed", own.status == 200,
                  f"HTTP {own.status}")


def check_logout(
    report: Report, discovery: dict[str, Any], client: dict[str, str], refresh: str
) -> None:
    print("\n=== 9. logout ends the session and revokes the refresh token ===")
    token_endpoint = str(discovery["token_endpoint"])
    end_session = str(discovery.get("end_session_endpoint", ""))
    report.ok("end_session endpoint is the realm logout",
              end_session.endswith("/protocol/openid-connect/logout"))
    # Backchannel logout on the same (internal) host as the token endpoint.
    logout_url = token_endpoint.rsplit("/token", 1)[0] + "/logout"
    out = call(logout_url, data={**client, "refresh_token": refresh})
    report.ok("backchannel logout accepted", out.status in {200, 204}, f"HTTP {out.status}")
    again = call(token_endpoint, data={**client, "grant_type": "refresh_token",
                                       "refresh_token": refresh})
    report.ok("refresh token refused after logout", again.status in {400, 401},
              f"HTTP {again.status} {again.json().get('error', '')}".strip())


def student_token(args: argparse.Namespace, discovery: dict[str, Any], secret: str) -> str | None:
    if not args.student_file:
        return None
    env = read_env(args.student_file)
    print("\n=== 7a. sign in as the synthetic student principal ===")
    tokens = login(Report(), args, discovery, secret,
                   (env["KEYCLOAK_STUDENT_USER"], env["KEYCLOAK_STUDENT_PASSWORD"]))
    return str(tokens["access_token"]) if tokens else ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for name in ("--issuer", "--api", "--client-id", "--client-secret-file", "--bootstrap-file"):
        parser.add_argument(name, required=True)
    # Keycloak pins the public issuer (KC_HOSTNAME) while this probe connects
    # over the internal address, so the expected iss can differ from --issuer.
    parser.add_argument("--expected-issuer", default=None)
    # Optional env file with KEYCLOAK_STUDENT_USER / KEYCLOAK_STUDENT_PASSWORD.
    parser.add_argument("--student-file", default=None)
    parser.add_argument("--redirect-uri", default="http://localhost:3000/auth/callback")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client_secret = read_env(args.client_secret_file)["KEYCLOAK_WEB_CLIENT_SECRET"]
    boot = read_env(args.bootstrap_file)
    username = boot["KEYCLOAK_BOOTSTRAP_USER"]
    issuer = args.issuer.rstrip("/")
    expected_issuer = (args.expected_issuer or args.issuer).rstrip("/")
    api = args.api.rstrip("/")
    report = Report()
    discovery = check_discovery(report, issuer, expected_issuer)
    if discovery is None:
        return 1
    print("\n=== 2-3. authorization code flow with PKCE and code exchange ===")
    tokens = login(report, args, discovery, client_secret,
                   (username, boot["KEYCLOAK_BOOTSTRAP_PASSWORD"]))
    if tokens is None:
        return 1
    access = str(tokens.get("access_token", ""))
    check_claims(report, access, expected_issuer, username)
    identity = check_api(report, api, access)
    student = student_token(args, discovery, client_secret)
    if student == "":
        report.ok("student principal signed in", False)
        student = None
    check_roles(report, api, access, str(identity.get("role", "")), student)
    check_tenant_switch(report, api, access, str(identity.get("id", "")))
    client = {"client_id": args.client_id, "client_secret": client_secret}
    check_logout(report, discovery, client, str(tokens.get("refresh_token", "")))
    if report.failures:
        print(f"\nRESULT: {len(report.failures)} check(s) failed: {report.failures}")
        return 1
    print("\nRESULT: all OIDC checks passed")
    return 0


def _form_action(html: str) -> str:
    """Extract the login form's action URL from the served page."""
    index = html.find('id="kc-form-login"')
    start = html.rfind("<form", 0, index) if index != -1 else -1
    if start == -1:
        return ""
    quoted = re.search(r'action="([^"]+)"', html[start : html.find(">", start) + 1])
    return html_unescape(quoted.group(1)) if quoted else ""


def _hidden_fields(html: str) -> dict[str, str]:
    """Collect the form's hidden inputs, which Keycloak requires to be echoed."""
    index = html.find('id="kc-form-login"')
    if index == -1:
        return {}
    end = html.find("</form>", index)
    block = html[index : end if end != -1 else len(html)]
    pattern = r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"'
    return {html_unescape(n): html_unescape(v) for n, v in re.findall(pattern, block)}


def _decode_claims(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        decoded = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _lifetime_seconds(claims: dict[str, Any]) -> int:
    try:
        return int(claims["exp"]) - int(claims["iat"])
    except (KeyError, TypeError, ValueError):
        return 10**9


if __name__ == "__main__":
    sys.exit(main())
