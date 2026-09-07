"""Contract lifecycle invariants."""
from __future__ import annotations


STATUSES = ("draft", "review", "approval", "signature", "active", "expired", "terminated")
TRANSITIONS = {
    "draft": frozenset({"review"}),
    "review": frozenset({"draft", "approval"}),
    "approval": frozenset({"review", "signature"}),
    "signature": frozenset({"approval", "active"}),
    "active": frozenset({"expired", "terminated"}),
    "expired": frozenset(),
    "terminated": frozenset(),
}


def require_transition(current: str, target: str) -> None:
    if target not in TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"Contract cannot move from {current} to {target}")


def next_statuses(current: str) -> tuple[str, ...]:
    return tuple(sorted(TRANSITIONS.get(current, frozenset())))
