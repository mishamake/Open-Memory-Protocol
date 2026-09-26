"""Exchange manifest and object-level receipt, after the Cognee draft §3.6.

The Cognee draft (Vasilije Markovic and the Cognee team) asks that every exchange begin with
a manifest (format and profile versions, object kinds, scope coverage, required extensions,
snapshot or selection) and end with a receipt naming what was accepted, transformed,
omitted, unresolved or rejected, with identity mappings and reasons.

COGX is Cognee's format and this module does not read or write it. These are plain JSON
shapes that carry the same information, so a COGX tool, or anything else, can compare them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from mappings._nest import now_iso

Outcome = Literal["accepted", "transformed", "omitted", "unresolved", "rejected"]

FORMAT = "omp-contextnest-exchange"
FORMAT_VERSION = "0.1"


@dataclass
class Manifest:
    """What an exchange claims to contain, written before any object."""

    source_authority: str
    """Origin authority, e.g. "contextnest" or an IBM system_id."""
    source_namespace: str
    """Namespace inside that authority, e.g. the nest name."""
    object_kinds: list[str]
    selection: str | None
    """The selector that chose the objects, or None for a complete snapshot."""
    profiles: list[str] = field(default_factory=lambda: ["contextnest-omp-0.1"])
    required_extensions: list[str] = field(default_factory=list)
    checkpoint: int | None = None
    """Context Nest checkpoint the export was read at (CN §7), when there is one."""
    format: str = FORMAT
    format_version: str = FORMAT_VERSION
    created_at: str = field(default_factory=now_iso)

    @property
    def completeness(self) -> str:
        # Cognee §3.6: absence from a partial export never implies deletion.
        return "snapshot" if self.selection is None else "selection"

    def to_json(self) -> dict[str, Any]:
        return {**asdict(self), "completeness": self.completeness}


@dataclass
class ReceiptEntry:
    origin_id: str
    outcome: Outcome
    local_id: str | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class Receipt:
    """Object-level result of one import or export (Cognee §3.6)."""

    direction: Literal["import", "export"]
    counterpart: str
    entries: list[ReceiptEntry] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def add(
        self,
        origin_id: str,
        outcome: Outcome,
        local_id: str | None = None,
        *reasons: str,
    ) -> ReceiptEntry:
        e = ReceiptEntry(origin_id, outcome, local_id, list(reasons))
        self.entries.append(e)
        return e

    def by_outcome(self, outcome: Outcome) -> list[ReceiptEntry]:
        return [e for e in self.entries if e.outcome == outcome]

    @property
    def identity_map(self) -> dict[str, str]:
        """Origin id -> local id, for every object that landed (Cognee §3.1)."""
        return {e.origin_id: e.local_id for e in self.entries if e.local_id}

    def to_json(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e.outcome] = counts.get(e.outcome, 0) + 1
        return {
            "direction": self.direction,
            "counterpart": self.counterpart,
            "created_at": self.created_at,
            "counts": counts,
            "entries": [asdict(e) for e in self.entries],
        }
