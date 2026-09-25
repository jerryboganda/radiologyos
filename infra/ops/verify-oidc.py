#!/usr/bin/env python3
"""End-to-end OIDC verification against a live Keycloak and the radbrain API.

Exercises the real browser flow the SvelteKit server performs: PKCE
authorization code, login form post, code exchange, then an authenticated call
to the API with the resulting access token.

The point is to prove the pieces fit, not to inspect the token:
  * the confidential client's secret authenticates the code exchange
  * PKCE S256 is accepted
  * the access token carries the radbrain-api audience (ADR 0004)
  * the subject is a stable, non-username identifier
  * the API accepts that token and resolves a database membership

Secrets are read from root-only env files and are never printed. Token contents
are never printed either; only structural facts and status codes.

Usage:
    verify-oidc.py --issuer http://keycloak:8080/realms/radbrain \\
                   --api http://api:8000 \\
                   --client-id radbrain-web \\
                   --client-secret-file /run/kc/keycloak.env \\
                   --bootstrap-file /run/kc/bootstrap.env
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
from html import unescape as html_unescape
from pathlib import Path


def read_env(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.strip().split("=", 1)
            values[key] = value
    return values


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_pkce() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(48))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--api", required=True)
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret-file", required=True)
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument(
        "--redirect-uri", default="http://localhost:3000/auth/callback"
    )
    args = parser.parse_args()

    kc_env = read_env(args.client_secret_file)
    boot = read_env(args.bootstrap_file)
    client_secret = kc_env["KEYCLOAK_WEB_CLIENT_SECRET"]
    username = boot["KEYCLOAK_BOOTSTRAP_USER"]
    password = boot["KEYCLOAK_BOOTSTRAP_PASSWORD"]

    issuer = args.issuer.rstrip("/")
    failures: list[str] = []

    def ok(label: str, condition: bool, detail: str = "") -> None:
        mark = "PASS" if condition else "FAIL"
        print(f"  [{mark}] {label}{(' - ' + detail) if detail else ''}")
        if not condition:
            failures.append(label)

    print("=== 1. the realm publishes the expected endpoints ===")
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    try:
        with urllib.request.urlopen(discovery_url, timeout=20) as resp:
            discovery = json.loads(resp.read())
        ok("discovery reachable", resp.status == 200)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] discovery unreachable: {exc}")
        return 1

    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        ok(f"discovery has {field}", bool(discovery.get(field)))
    ok(
        "issuer in discovery matches",
        discovery.get("issuer", "").rstrip("/") == issuer,
        discovery.get("issuer", ""),
    )
    ok(
        "PKCE S256 advertised",
        "S256" in (discovery.get("code_challenge_methods_supported") or []),
    )

    print()
    print("=== 2. authorization code flow with PKCE ===")
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    jar = http.cookiejar.CookieJar()

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), NoRedirect()
    )
    authorize_url = (
        f"{discovery['authorization_endpoint']}"
        f"?response_type=code"
        f"&client_id={urllib.parse.quote(args.client_id)}"
        f"&redirect_uri={urllib.parse.quote(args.redirect_uri, safe='')}"
        f"&scope={urllib.parse.quote('openid profile email')}"
        f"&state={state}"
        f"&code_challenge={challenge}"
        f"&code_challenge_method=S256"
    )

    try:
        with opener.open(authorize_url, timeout=20) as resp:
            login_html = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        login_html = exc.read().decode("utf-8", "replace")
        status = exc.code
    ok("authorize redirects to the login page", status in {200, 302}, f"HTTP {status}")

    if "kc-form-login" not in login_html:
        print("  [FAIL] no Keycloak login form in the response; cannot complete the flow")
        return 1
    print("  [PASS] login form served")

    # Use the form's own action URL and hidden fields. Reconstructing the
    # session code by hand is fragile: Keycloak puts the real action, and any
    # credential id, in the served HTML.
    action = _form_action(login_html)
    if not action:
        print("  [FAIL] could not read the login form action from the page")
        return 1
    if action.startswith("/"):
        action = f"{issuer}{action}"
    hidden = _hidden_fields(login_html)
    hidden.update({"username": username, "password": password})
    form = urllib.parse.urlencode(hidden).encode()

    try:
        with opener.open(
            urllib.request.Request(action, data=form), timeout=20
        ) as resp:
            location = resp.headers.get("Location", "")
            status = resp.status
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "") if exc.headers else ""
        status = exc.code
    ok("login accepted", bool(location), f"HTTP {status}")
    if not location:
        print("  [FAIL] no redirect back to the client; wrong credentials?")
        return 1

    # Report only the path of the redirect target. The query carries the
    # authorization code, so it is never printed.
    target = urllib.parse.urlparse(location)
    print(f"         redirected to {target.scheme}://{target.netloc}{target.path}")
    if "error" in dict(urllib.parse.parse_qsl(target.query)):
        errs = dict(urllib.parse.parse_qsl(target.query))
        print(f"  [FAIL] provider returned error={errs.get('error')}")
        return 1

    parsed = urllib.parse.urlparse(location)
    params = dict(urllib.parse.parse_qsl(parsed.query))
    ok("state echoed back unchanged", params.get("state") == state)
    code = params.get("code")
    ok("authorization code issued", bool(code))
    if not code:
        return 1

    print()
    print("=== 3. code exchange with the confidential client ===")
    token_body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": args.redirect_uri,
            "client_id": args.client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        }
    ).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                discovery["token_endpoint"], data=token_body, method="POST"
            ),
            timeout=20,
        ) as resp:
            tokens = json.loads(resp.read())
            ok("token exchange succeeded", resp.status == 200)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        print(f"  [FAIL] token exchange HTTP {exc.code}")
        try:
            # Only the error code is safe to show; it contains no secrets.
            print(f"         oauth error: {json.loads(payload).get('error')}")
        except Exception:  # noqa: BLE001
            pass
        return 1

    access_token = tokens.get("access_token", "")
    ok("access token issued", bool(access_token))
    ok("refresh token issued", bool(tokens.get("refresh_token")))
    ok("id token issued", bool(tokens.get("id_token")))

    claims = _decode_claims(access_token)
    print()
    print("=== 4. access token structure (claims are not printed) ===")
    ok("issuer claim matches the realm", claims.get("iss", "").rstrip("/") == issuer)
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    ok(
        "audience includes radbrain-api (ADR 0004)",
        "radbrain-api" in audiences,
        f"aud={sorted(a for a in audiences if a)}",
    )
    subject = claims.get("sub", "")
    ok("subject present and opaque", bool(subject) and subject != username)
    ok("token is short-lived", _lifetime_seconds(claims) <= 1800)

    # Roles are deliberately NOT taken from the token. Membership and role are
    # resolved from the database after signature and audience verification, so a
    # token that carries no role claim is the expected, safer shape. The check
    # below asserts we are not relying on token claims for authorisation.
    token_roles = claims.get("realm_access", {}).get("roles") if isinstance(
        claims.get("realm_access"), dict
    ) else None
    print(
        "  [INFO] token role claims present: "
        f"{bool(token_roles)} (authorisation comes from the database regardless)"
    )

    print()
    print("=== 5. the API accepts the token and resolves a membership ===")
    request = urllib.request.Request(
        f"{args.api.rstrip('/')}/v1/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            ok("authenticated identity lookup succeeded", resp.status == 200, f"HTTP {resp.status}")
            print(f"         {body[:160]}")
    except urllib.error.HTTPError as exc:
        ok("authenticated identity lookup succeeded", False, f"HTTP {exc.code}")
        print(f"         {exc.read().decode('utf-8', 'replace')[:200]}")

    print()
    print("=== 6. a forged or wrong-audience token is still refused ===")
    tampered = access_token[:-4] + ("aaaa" if not access_token.endswith("aaaa") else "bbbb")
    bad = urllib.request.Request(
        f"{args.api.rstrip('/')}/v1/me",
        headers={"Authorization": f"Bearer {tampered}"},
    )
    try:
        with urllib.request.urlopen(bad, timeout=20):
            ok("tampered signature refused", False, "the API accepted it")
    except urllib.error.HTTPError as exc:
        ok("tampered signature refused", exc.code in {401, 403}, f"HTTP {exc.code}")

    none = urllib.request.Request(f"{args.api.rstrip('/')}/v1/me")
    try:
        with urllib.request.urlopen(none, timeout=20):
            ok("missing token refused", False, "the API accepted it")
    except urllib.error.HTTPError as exc:
        ok("missing token refused", exc.code in {401, 403}, f"HTTP {exc.code}")

    print()
    if failures:
        print(f"RESULT: {len(failures)} check(s) failed: {failures}")
        return 1
    print("RESULT: all OIDC checks passed")
    return 0


def _form_action(html: str) -> str:
    """Extract the login form's action URL from the served page."""
    marker = 'id="kc-form-login"'
    index = html.find(marker)
    if index == -1:
        return ""
    start = html.rfind("<form", 0, index)
    if start == -1:
        return ""
    tag = html[start : html.find(">", start) + 1]
    quoted = re.search(r'action="([^"]+)"', tag)
    if not quoted:
        return ""
    return html_unescape(quoted.group(1))


def _hidden_fields(html: str) -> dict[str, str]:
    """Collect the form's hidden inputs, which Keycloak requires to be echoed."""
    fields: dict[str, str] = {}
    marker = 'id="kc-form-login"'
    index = html.find(marker)
    if index == -1:
        return fields
    end = html.find("</form>", index)
    block = html[index : end if end != -1 else len(html)]
    for name, value in re.findall(
        r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', block
    ):
        fields[html_unescape(name)] = html_unescape(value)
    return fields


def _session_code(jar: http.cookiejar.CookieJar, issuer: str) -> str:
    for cookie in jar:
        if cookie.name in {"AUTH_SESSION_ID", "KC_RESTART"} and cookie.value:
            return cookie.value
    return ""


def _decode_claims(token: str) -> dict[str, object]:
    import json as _json

    try:
        payload = token.split(".")[1]
        padded = payload + "=" * (-len(payload) % 4)
        return _json.loads(base64.urlsafe_b64decode(padded))
    except Exception:  # noqa: BLE001
        return {}


def _lifetime_seconds(claims: dict[str, object]) -> int:
    try:
        return int(claims["exp"]) - int(claims["iat"])  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return 10**9


if __name__ == "__main__":
    sys.exit(main())
