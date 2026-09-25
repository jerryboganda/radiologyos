from __future__ import annotations

from uuid import UUID

from apps.api.app.preview.state import PreviewState


def billing_status(_state: PreviewState, _tenant_id: UUID) -> dict[str, object]:
    return {
        "provider": "mock_stripe_test_mode",
        "status": "preview_only",
        "message": "No Stripe customer, checkout, portal, or charge exists in preview mode.",
    }


def markdown_export(state: PreviewState, tenant_id: UUID, owner_id: UUID) -> str:
    lines = [
        "# radbrain preview export",
        "",
        "Synthetic local export. Not a Core Library artifact.",
        "",
    ]
    for source in state.sources(tenant_id):
        if source.owner_id != owner_id:
            continue
        lines.extend([f"## {source.title}", "", f"Source: `{source.id}`", ""])
        for chunk in state.source_chunks(tenant_id, source.id):
            lines.extend(
                [
                    chunk.text,
                    "",
                    f"Citation: `{source.id}` p. {chunk.page_no} block `{chunk.block_start}`",
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"


def capabilities() -> list[dict[str, str]]:
    blocked_note = "Staging acceptance and approvals remain open."
    preview_note = "Synthetic local contract implemented; not accepted."
    return (
        [{"slice": letter, "status": "blocked", "note": blocked_note} for letter in "ABCD"]
        + [
            {"slice": letter, "status": "preview", "note": preview_note}
            for letter in "EFGHIJKLMNOPQRSTUVWXY"
        ]
        + [
            {
                "slice": "Z",
                "status": "blocked",
                "note": "Release audit requires all milestone evidence and approvals.",
            }
        ]
    )


def local_mode_status() -> dict[str, object]:
    return {
        "backend": "mock",
        "certified": False,
        "message": (
            "Local model certification and provider/privacy approval remain release blockers."
        ),
    }


def release_audit() -> dict[str, object]:
    return {
        "status": "blocked",
        "completed": ("preview:contracts", "preview:synthetic-boundaries"),
        "blocked": (
            "m0:staging-acceptance",
            "m1:staging-evidence",
            "m2:staging-evidence",
            "m3:staging-evidence",
            "m4:staging-evidence",
            "m5:staging-evidence",
            "m6:staging-evidence",
            "m7:staging-evidence",
            "release:human-approvals",
        ),
    }
