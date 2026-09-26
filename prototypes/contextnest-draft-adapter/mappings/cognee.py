"""Context Nest  <->  the Cognee six-part semantic core (Cognee draft v0.1, Vasilije Markovic
and the Cognee team).

The Cognee draft asks for meaning, not a file format: identity and revision; content,
origin and evidence; scope, ownership and authority; provenance and lineage; time,
lifecycle and deletion; exchange capability and fidelity. It asks for published mappings
that list unmappable fields, and for fixtures two independent implementations exchange
both ways. This module is the Context Nest side of that:

- `SEMANTIC_CORE`: a declarative table, one row per requirement, naming the Context Nest
  carrier, whether it is carried today, proposed, or not carried, and why.
- `core_view(nest, node_id)`: one node's six parts, read from `ctx`.
- `export_manifest(nest, selector)`: a manifest and a per-object receipt for a selection.

COGX is Cognee's format. Nothing here reads, writes or depends on it or on cognee.
"""

from __future__ import annotations

from typing import Any, Literal

from mappings._nest import NestIO, VersionEntry
from mappings.exchange import Manifest, Receipt

Carried = Literal["carried", "partial", "proposed", "not carried"]

# (part, requirement, CN carrier, status, note)
SEMANTIC_CORE: list[dict[str, str]] = [
    # 3.1 identity and revision
    {"part": "identity", "requirement": "origin-qualified logical identity",
     "carrier": "contextnest://<id> (namespace per CN §4.0)", "status": "partial",
     "note": "The path is the identity inside a nest. The nest's own namespace is optional "
             "(CN §4.0), so an exporter adds the authority in the manifest."},
    {"part": "identity", "requirement": "immutable revision identity",
     "carrier": "version + chain_hash in history; contextnest://<id>@<checkpoint>",
     "status": "carried", "note": "History is append-only and hash-chained (CN §6, §8)."},
    {"part": "identity", "requirement": "origin-to-local mapping on import",
     "carrier": "version note + metadata.omp.<draft>.origin (these mappings)",
     "status": "partial", "note": "Not a CN field; the mappings keep it in metadata."},
    {"part": "identity", "requirement": "different content under one revision is a conflict",
     "carrier": "content_hash per version; ctx verify", "status": "carried",
     "note": "ctx verify reports content_hash_mismatch."},
    # 3.2 content, origin and evidence
    {"part": "evidence", "requirement": "distinguish source artifact / transcript / human "
     "assertion / machine-derived", "carrier": "type (source, document, ...), client.agent, "
     "derived_from", "status": "partial",
     "note": "type:source marks a source runbook, not a stored artifact. No transcript type. "
             "Human vs machine is read from whether a write carried client.agent. See "
             "evidence_role()."},
    {"part": "evidence", "requirement": "derived memory with unavailable evidence says so",
     "carrier": "derived_from entries that no longer resolve", "status": "partial",
     "note": "Detectable (the URI does not resolve); not flagged in the node."},
    {"part": "evidence", "requirement": "text baseline; typed media descriptors",
     "carrier": "Markdown body; type:pdf with a sidecar", "status": "partial", "note": ""},
    # 3.3 scope, ownership and authority
    {"part": "scope", "requirement": "subject, owner, author/agent, origin system, context",
     "carrier": "edited_by, client.agent, author (optional key)", "status": "partial",
     "note": "Author and agent are carried per version. Subject, owner and applicable "
             "context have no CN key."},
    {"part": "scope", "requirement": "portable policy (principals, actions, retention)",
     "carrier": "none", "status": "not carried",
     "note": "CN draft §1 leaves read permission out on purpose and asks the group to argue "
             "it (CN §10 q1)."},
    {"part": "scope", "requirement": "import does not grant instruction authority",
     "carrier": "status: published gate", "status": "partial",
     "note": "An imported node is only served once published; the harness still decides "
             "what counts as an instruction."},
    # 3.4 provenance and lineage
    {"part": "lineage", "requirement": "derivation names the input revisions themselves",
     "carrier": "derived_from with pinned URIs (id@N)", "status": "carried",
     "note": "A floating derived_from URI names the node, not the revision; a pinned URI names one revision."},
    {"part": "lineage", "requirement": "transformation, actor, model, time",
     "carrier": "history: edited_by, edited_at, note, client", "status": "carried", "note": ""},
    {"part": "lineage", "requirement": "consolidation names all inputs",
     "carrier": "derived_from (list)", "status": "carried", "note": ""},
    {"part": "lineage", "requirement": "W3C PROV alignment", "carrier": "none", "status":
     "not carried", "note": "Maps cleanly (node = entity, publish = activity, edited_by = "
     "agent, derived_from = wasDerivedFrom) but CN does not emit PROV."},
    # 3.5 time, lifecycle and deletion
    {"part": "lifecycle", "requirement": "recording time vs application time",
     "carrier": "edited_at, published_at, checkpoint at", "status": "partial",
     "note": "Four recording clocks; no valid-time pair (CN §5.1, open question §10 q4)."},
    {"part": "lifecycle", "requirement": "active / superseded / invalidated / expired / "
     "deleted", "carrier": "published / later version / rejected / expires_at / forgotten",
     "status": "partial", "note": "expires_at and forgotten are proposed (CN §6.3), not in "
     "ctx yet. rejected is terminal and cannot be republished."},
    {"part": "lifecycle", "requirement": "lifecycle events with id, target, actor, time, "
     "reason", "carrier": "version entries; checkpoint entries", "status": "partial",
     "note": "Publishes are events. Metadata-only transitions (published -> rejected) are "
             "not recorded as events (CN A.1)."},
    {"part": "lifecycle", "requirement": "tombstone prevents resurrection",
     "carrier": "forget: tombstoned history entries, status: forgotten", "status": "proposed",
     "note": "CN §6.3.4. Being built in ctx; see fixtures/resurrection.json."},
    {"part": "lifecycle", "requirement": "historical reads explicit",
     "carrier": "contextnest://<id>@<checkpoint>", "status": "carried", "note": ""},
    # 3.6 exchange capability and fidelity
    {"part": "exchange", "requirement": "manifest (versions, kinds, scope, extensions, "
     "snapshot vs selection)", "carrier": "exchange.Manifest (these mappings)",
     "status": "partial", "note": "The nest directory is its own export (CN §6.2); the "
     "manifest is added by the mapping, not by ctx."},
    {"part": "exchange", "requirement": "object-level receipt", "carrier":
     "exchange.Receipt (these mappings)", "status": "partial", "note": ""},
    {"part": "exchange", "requirement": "verify after transfer", "carrier": "ctx verify on "
     "the receiving nest", "status": "carried", "note": "Directory copy only; a mapped "
     "import gets fresh hashes."},
    {"part": "exchange", "requirement": "copy vs move vs federation", "carrier":
     "cp of the directory; namespaces (CN §4.0)", "status": "partial",
     "note": "Move is not an operation; federation is specified, partly implemented."},
]

UNMAPPABLE: dict[str, str] = {
    row["requirement"]: row["note"] for row in SEMANTIC_CORE if row["status"] == "not carried"
}


def evidence_role(node_type: str, entry: VersionEntry | None, derived_from: list[str]) -> str:
    """Cognee §3.2 epistemic role, read from what a node carries. A role, not a truth label."""
    if node_type == "source":
        return "source_artifact_reference"
    if derived_from:
        return "machine_derived" if entry and entry.client.get("agent") else "derived"
    if entry and entry.client.get("agent"):
        return "machine_derived"
    return "human_assertion"


def _pinned(nest: NestIO, node_id: str, version: int) -> str | None:
    cp = nest.checkpoint_of(node_id, version)
    return None if cp is None else f"contextnest://{node_id}@{cp}"


def core_view(nest: NestIO, node_id: str) -> dict[str, Any]:
    """One node described in the six parts. Every value is read from ctx."""
    live = nest.read(node_id)
    hist = nest.history(node_id)
    published = [e for e in hist if e.published_at]
    tip = published[-1] if published else None
    derived = [str(d) for d in live.frontmatter.get("derived_from") or []]
    state = {
        "published": "active",
        "rejected": "invalidated",
        "forgotten": "deleted",
    }.get(live.status, "not_current")
    return {
        "identity": {
            "authority": "contextnest",
            "namespace": nest.name,
            "id": live.uri,
            "revisions": [
                {
                    "version": e.version,
                    "pinned": _pinned(nest, node_id, e.version),
                    "chain_hash": e.chain_hash,
                }
                for e in published
            ],
        },
        "evidence": {
            "role": evidence_role(str(live.frontmatter.get("type", "document")), tip, derived),
            "media": "text/markdown",
        },
        "scope": {
            "author": tip.edited_by if tip else None,
            "agent": tip.client.get("agent") if tip else None,
            "origin_system": (live.omp.get("ibm") or {}).get("origin")
            or f"contextnest:{nest.name}",
            "policy": None,  # not carried, see SEMANTIC_CORE
        },
        "lineage": {
            "derived_from": derived,
            "inputs_pinned": all("@" in d for d in derived),
            "events": [
                {"version": e.version, "actor": e.edited_by, "at": e.published_at, "note": e.note}
                for e in published
            ],
        },
        "lifecycle": {
            "state": state,
            "status": live.status,
            "created_at": live.frontmatter.get("created_at"),
            "updated_at": live.frontmatter.get("updated_at"),
            "valid_time": None,  # not carried (CN §5.1)
        },
        "exchange": {"profiles": ["contextnest-omp-0.1"], "verify": "ctx verify"},
    }


def export_manifest(nest: NestIO, selector: str | None = None) -> tuple[Manifest, Receipt]:
    """Manifest plus receipt for what a Cognee-style receiver would get from this selection:
    which objects travel as they are, which are transformed (and how), which are left out."""
    receipt = Receipt("export", counterpart="cognee-semantic-core-0.1")
    ids = nest.ids(include_rejected=True) if selector is None else nest.served(selector)
    for node_id in ids:
        v = core_view(nest, node_id)
        uri = v["identity"]["id"]
        if not v["identity"]["revisions"]:
            receipt.add(uri, "omitted", None, f"status {v['lifecycle']['status']}, never published")
            continue
        reasons = ["policy not carried (CN leaves permissions out)", "no valid-time pair"]
        if v["lineage"]["derived_from"] and not v["lineage"]["inputs_pinned"]:
            reasons.append("derived_from names nodes, not revisions (floating URIs)")
        if v["lifecycle"]["state"] == "invalidated":
            reasons.append("rejected: invalidation time not recorded (metadata-only transition)")
        receipt.add(uri, "transformed", uri, *reasons)
    manifest = Manifest(
        source_authority="contextnest",
        source_namespace=nest.name,
        object_kinds=["contextnest-node"],
        selection=selector,
        checkpoint=nest.latest_checkpoint(),
    )
    return manifest, receipt
