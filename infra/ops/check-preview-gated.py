#!/usr/bin/env python3
"""Assert that the retired preview surface is absent and billing stays gated.

Runs from inside the platform network. ADR 0031 removed the in-memory preview
surface, so every former ``/v1/preview/*`` route must answer 404 whatever the
credential, including spoofed development identity headers. A 200 would mean
the surface came back; a 401/403 would mean a router is still mounted.

Parked billing (ADR 0011) must refuse an anonymous caller: 401/403 when it is
enabled, 404 when it is off.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://radbrain-api:8000"

ABSENT = {404}
GATED = {401, 403, 404}
SPOOF = {
    "x-user-id": "10000000-0000-0000-0000-000000000001",
    "x-tenant-id": "20000000-0000-0000-0000-000000000002",
    "x-role": "superadmin",
}

PROBES: list[tuple[str, str, dict[str, str], set[int]]] = [
    ("GET", "/v1/preview/sources", {}, ABSENT),
    ("GET", "/v1/preview/capabilities", {}, ABSENT),
    ("POST", "/v1/preview/search", {}, ABSENT),
    ("POST", "/v1/preview/tutor/ask", {}, ABSENT),
    ("GET", "/v1/preview/export/markdown", {}, ABSENT),
    ("GET", "/v1/preview/sources", SPOOF, ABSENT),
    ("GET", "/v1/billing/subscription", {}, GATED),
    ("GET", "/v1/me", {}, {401}),
]


def probe(method: str, path: str, headers: dict[str, str]) -> int:
    data = b"{}" if method == "POST" else None
    if not BASE.startswith(("http://", "https://")):
        raise ValueError("only http(s) bases are probed")
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:  # nosec B310 - http(s) only
            return int(resp.status)
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001
        print(f"  probe error on {method} {path}: {exc}")
        return 0


def main() -> int:
    failures = 0
    print("=== retired preview and parked billing probes ===")
    for method, path, headers, allowed in PROBES:
        label = "with dev headers" if headers else "no credential"
        code = probe(method, path, headers)
        verdict = "PASS" if code in allowed else "FAIL"
        if code not in allowed:
            failures += 1
        wanted = "/".join(str(c) for c in sorted(allowed))
        print(f"  [{verdict}] {method:<5} {path:<30} {label:<16} -> HTTP {code} (want {wanted})")

    print()
    if failures:
        print(f"RESULT: {failures} probe(s) failed")
        return 1
    print("RESULT: the preview surface is absent and billing is gated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
