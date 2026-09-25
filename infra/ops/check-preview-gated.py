#!/usr/bin/env python3
"""Assert that the preview surface is only reachable behind authentication.

Runs from inside the platform network. The point is the negative case: with no
credential at all, every preview route must refuse. A 200 here would mean the
non-release surface is open to the internet, which ADR 0009 does not permit.

Development header identity is also probed, because it must not become a
production authentication path.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://radbrain-api:8000"

# Any of 401/403 proves the route is gated. 404 would mean the surface is absent,
# which is stricter still but is not the state this deployment is in.
GATING = {401, 403}
ABSENT = {404}

PROBES: list[tuple[str, str, dict[str, str]]] = [
    ("GET", "/v1/preview/sources", {}),
    ("GET", "/v1/preview/capabilities", {}),
    ("POST", "/v1/preview/search", {}),
    ("POST", "/v1/preview/tutor/ask", {}),
    ("GET", "/v1/preview/export/markdown", {}),
    ("GET", "/v1/billing/subscription", {}),
    (
        "GET",
        "/v1/preview/sources",
        {
            "x-user-id": "10000000-0000-0000-0000-000000000001",
            "x-tenant-id": "20000000-0000-0000-0000-000000000002",
            "x-role": "superadmin",
        },
    ),
]

ALLOWED = GATING | ABSENT


def probe(method: str, path: str, headers: dict[str, str]) -> int:
    data = b"{}" if method == "POST" else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception as exc:  # noqa: BLE001
        print(f"  probe error on {method} {path}: {exc}")
        return 0


def main() -> int:
    failures = 0
    print("=== unauthenticated and header-identity probes ===")
    for method, path, headers in PROBES:
        label = "with dev headers" if headers else "no credential"
        code = probe(method, path, headers)
        verdict = "PASS" if code in ALLOWED else "FAIL"
        if code not in ALLOWED:
            failures += 1
        print(f"  [{verdict}] {method:<5} {path:<34} {label:<16} -> HTTP {code}")

    print()
    if failures:
        print(f"RESULT: {failures} probe(s) were not gated")
        return 1
    print("RESULT: every preview and billing route is gated behind authentication")
    return 0


if __name__ == "__main__":
    sys.exit(main())
