"""Shared fixtures for the M1-M7 eval gates.

Each gate gets its own PreviewState instance so gates cannot leak state into one
another, and every gate builds two tenants so a cross-tenant negative is always
available to assert against.
"""

from __future__ import annotations

from uuid import UUID

from apps.api.app.preview.knowledge import ensure_knowledge
from apps.api.app.preview.library import ingest_source
from apps.api.app.preview.state import PreviewState

TENANT_A = UUID("30000000-0000-0000-0000-00000000000a")
TENANT_B = UUID("30000000-0000-0000-0000-00000000000b")
OWNER_A = UUID("10000000-0000-0000-0000-00000000000a")
OWNER_B = UUID("10000000-0000-0000-0000-00000000000b")

CHEST = """# Chest radiography

Ground-glass opacity on the right lower zone suggests an alveolar filling process.

## Pleura

A pleural effusion blunts the costophrenic angle and layers on decubitus views.

## Mediastinum

Loss of the hilar point suggests hilar lymphadenopathy.
"""

HEAD = """# Head CT

Subarachnoid haemorrhage is hyperdense on non-contrast CT within six hours.

## Stroke

MCA territory infarction produces cortical loss and sulcal effacement.
"""

ABDOMEN = """# Abdomen radiography

Pneumoperitoneum under the diaphragm is a surgical emergency.
"""

# Figures are only produced from an explicit `[[figure:<modality>]]` marker
# whose paragraph carries a caption line.
FIGURES = """# Synthetic figure plate

[[figure:chest-xray]]
Synthetic chest radiograph with a right lower zone ground-glass opacity.

[[figure:axial-ct]]
Synthetic axial head CT demonstrating a hyperdense subarachnoid haemorrhage.
"""


def new_state() -> PreviewState:
    return PreviewState()


def seed(
    state: PreviewState,
    tenant_id: UUID = TENANT_A,
    owner_id: UUID = OWNER_A,
) -> None:
    """Ingest one multi-section synthetic source and derive knowledge."""
    ingest_source(
        state,
        tenant_id,
        owner_id,
        title="Synthetic chest notes",
        kind="note",
        content=CHEST,
        idempotency_key="eval-chest",
    )
    ensure_knowledge(state, tenant_id, owner_id)
