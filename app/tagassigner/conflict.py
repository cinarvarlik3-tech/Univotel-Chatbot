"""
Option A — timestamp conflict rule (§6.7 of tagassigner-v1-spec.md).

TagAssigner may change a conflict-managed field ONLY if there is in-chat evidence
timestamped STRICTLY newer than the field's last-set time. Strict "newer-than" (not
">=") prevents TagAssigner from churning its own value each run.

Conflict-managed fields: ilgili_otel, ziyaret (label — handled via label_resolver).
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional


def may_overwrite(
    proposed_value: Optional[str],
    current_value: Optional[str],
    field_set_at: Optional[datetime],
    newest_evidence_at: Optional[datetime],
) -> bool:
    """
    Returns True if TagAssigner is allowed to change this field.

    Rules:
    - If no current value → always allow (field has never been set).
    - If proposed_value == current_value → no change needed, trivially allowed.
    - If field has no _set_at timestamp → allow (legacy / pre-TagAssigner row).
    - Otherwise: allow only if newest_evidence_at STRICTLY > field_set_at.
    """
    if current_value is None:
        return True
    if proposed_value == current_value:
        return True
    if field_set_at is None:
        return True
    if newest_evidence_at is None:
        return False
    return newest_evidence_at > field_set_at
