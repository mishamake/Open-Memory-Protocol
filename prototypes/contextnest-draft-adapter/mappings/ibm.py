"""Context Nest node  <->  IBM MemoryRecord (IBM draft v0.1, Gabe Goodhart and IBM).

Uses the IBM prototype's own `MemoryRecord`, `Lifecycle`, `Provenance` and `ExportBundle`
(prototypes/ibm-draft-memory-records), so an export from a nest is an IBM bundle that the
IBM `MemoryStore.import_bundle` accepts as is, and an IBM `MemoryStore.export()` is what
`import_bundle` below reads.

The two drafts agree on the important thing: a memory is never edited in place. IBM writes a
new record and invalidates the old one; Context Nest appends a version to the node's
history. So one Context Nest node with N published versions becomes an override chain of
N IBM records, and an override chain becomes one node with N versions.

    CN                                   IBM
    one published version of a node      one MemoryRecord
    contextnest://<id>@<checkpoint>      record.id   (the pinned URI of that version)
    body at that version                 record.body
    history.edited_by                    lifecycle.author
    client.agent / client.model / note   lifecycle.provenance (agent, model, how)
    history.published_at                 lifecycle.created_at
    next version's published_at          lifecycle.invalidated_at (superseded)
    status: rejected (tip)               lifecycle.invalidated_at (invalidated)
    version                              lifecycle.version (integer comparator)
    derived_from                         lifecycle.source_material
    previous version's pinned URI        record.supersedes
    tags, type, title, description       semantic_tags ("#x", "type:x", "title:x",
                                         "description:x", same convention as the IBM
                                         prototype's Packer bridge)
    node id                              scope tag "node:<id>" (like the bridge's "path:")

Versions, checkpoints and hashes are read from `ctx` and written by `ctx publish`; nothing
here computes them.
"""

from __future__ import annotations

import re
from typing import Any

from contextnest_adapter.ctx import CtxError
from ibm_memory.schema import ExportBundle, Lifecycle, MemoryRecord, Provenance

from mappings._nest import (
    PLAIN_TYPES,
    Node,
    NestIO,
    VersionEntry,
    as_cn_tag,
    canon_body,
    is_cn_tag,
    iso,
    now_iso,
    slug_path,
)
from mappings.exchange import Manifest, Receipt

TAG_CONTEXT = {
    "#": "Context Nest semantic tag (CN §1.5 tags), shared taxonomy of the source nest",
    "type:": "Context Nest structural type (CN §1.6)",
    "title:": "Context Nest node title",
    "description:": "Context Nest one-line description",
    "node:": "scope tag: the Context Nest node id every revision in this chain belongs to",
}

UNMAPPABLE: dict[str, dict[str, str]] = {
    "cn_to_ibm": {
        "status draft / pending_review / approved": "IBM records have no approval state. "
        "Revisions that were never published are left out of the export and listed in the "
        "receipt as omitted.",
        "edited_at": "IBM has one creation clock. created_at is the version's published_at "
        "(when agents could first see it); edited_at is dropped.",
        "checkpoint (whole-nest state)": "Kept only inside record.id as '@N'. IBM has no "
        "graph-level snapshot, so a set of records does not say which versions were live "
        "together.",
        "content_hash, chain_hash, checksum": "IBM records carry no integrity fields. The "
        "receiving side cannot verify the chain; an import back into a nest gets new hashes "
        "from ctx.",
        "in-prose links (reference edges)": "Left in the body text. IBM has no edge type.",
        "packs and selectors": "No IBM equivalent. An export can be chosen by a selector; "
        "the manifest records which one.",
        "time of a published -> rejected transition": "Metadata-only transitions cut no "
        "version (CN A.1), so history does not record when it happened. The exporter stamps "
        "the export time and says so in the receipt.",
        "client.session_id and custom client keys": "IBM provenance has agent, model and "
        "free-text 'how' only.",
    },
    "ibm_to_cn": {
        "scope_tags": "Context Nest leaves read permission out of the protocol (CN draft §1). "
        "Scope tags are kept under metadata.omp.ibm.scope_tags so they survive a round trip, "
        "but ctx does not enforce them. Retained, not understood.",
        "ScopePolicy (ACLs)": "Not part of an IBM bundle, so nothing to map.",
        "created_at of each revision": "ctx stamps edited_at and published_at when the "
        "revision is sealed. The original instant is kept in the version note and in "
        "metadata.omp.ibm.created_at.",
        "invalidated_at of a superseded record": "Expressed by the next version existing; "
        "the instant itself is not carried.",
        "semantic tags outside CN tag grammar (spaces, dots)": "Kept in "
        "metadata.omp.ibm.semantic_tags only; not usable in selectors.",
        "Delete": "ctx delete removes a node and its history. The importer never deletes; "
        "an erased record is simply absent from a bundle, which does not imply deletion "
        "(Cognee §3.6).",
    },
}

_NOTE = re.compile(r"omp-import created_at=(\S+) origin=(.+)$")


def _pinned(nest: NestIO, node_id: str, version: int) -> str:
    cp = nest.checkpoint_of(node_id, version)
    return f"contextnest://{node_id}@{cp}" if cp is not None else f"contextnest://{node_id}"


# --------------------------------------------------------------------------- export


def _created(entry: VersionEntry) -> str:
    """IBM created_at for a version: the original instant if the version came from an IBM
    import (kept in the note), else when ctx published it."""
    m = _NOTE.match(entry.note or "")
    return m.group(1) if m else iso(entry.published_at or entry.edited_at) or now_iso()


def record_for_version(
    node: Node,
    entry: VersionEntry,
    *,
    record_id: str,
    supersedes: str | None,
    invalidated_at: str | None,
) -> MemoryRecord:
    """One published version of a node as an IBM MemoryRecord."""
    ibm = node.omp.get("ibm") if isinstance(node.omp.get("ibm"), dict) else None
    imported = _NOTE.match(entry.note or "")
    if ibm:  # came from an IBM system: give its own tags back
        semantic = list(ibm.get("semantic_tags") or [])
        scope = list(ibm.get("scope_tags") or [])
        source = list(ibm.get("source_material") or [])
    else:
        ntype = node.frontmatter.get("type", "document")
        semantic = [*node.tags, f"type:{ntype}", f"title:{node.title}"]
        if node.frontmatter.get("description"):
            semantic.append(f"description:{node.frontmatter['description']}")
        scope = []
        source = [str(s) for s in node.frontmatter.get("derived_from") or []]
    scope = sorted({*scope, f"node:{node.id}"})
    ai_agent = entry.client.get("agent")
    ai_model = entry.client.get("model")
    how = entry.note
    if imported:
        how = (ibm or {}).get("how") or how
    return MemoryRecord(
        id=record_id,
        body=canon_body(node.body),
        lifecycle=Lifecycle(
            author=entry.edited_by or str(node.frontmatter.get("author") or "unknown"),
            provenance=Provenance(
                ai_used=bool(ai_agent or ai_model or entry.client.get("ai_used") == "true"),
                model=ai_model,
                agent=ai_agent,
                how=how,
            ),
            created_at=_created(entry),
            invalidated_at=invalidated_at,
            version=entry.version,
            source_material=source,
        ),
        semantic_tags=sorted(set(semantic)),
        scope_tags=scope,
        supersedes=supersedes,
    )


def export_bundle(
    nest: NestIO, selector: str | None = None
) -> tuple[ExportBundle, Manifest, Receipt]:
    """Export published history as an IBM bundle, with a manifest and a receipt.

    `selector=None` exports every node (a snapshot, rejected nodes included, as invalidated
    records). A selector exports only what the resolver serves for it (a selection).
    """
    name = nest.name
    receipt = Receipt("export", counterpart="ibm-omp-0.1")
    ids = nest.ids(include_rejected=True) if selector is None else nest.served(selector)
    records: list[MemoryRecord] = []
    for node_id in ids:
        live = nest.read(node_id)
        published = [e for e in nest.history(node_id) if e.published_at]
        if not published:
            receipt.add(
                live.uri, "omitted", None,
                f"status {live.status}, never published; IBM records have no approval state",
            )
            continue
        if live.status not in ("published", "rejected"):
            receipt.add(
                live.uri, "omitted", None,
                f"live revision is {live.status}; only published versions are exported",
            )
        prev_id: str | None = None
        for i, entry in enumerate(published):
            node = nest.reconstruct(node_id, entry.version)
            rid = _pinned(nest, node_id, entry.version)
            reasons: list[str] = []
            if i + 1 < len(published):
                inval = _created(published[i + 1])
            elif live.status == "rejected":
                inval = now_iso()
                reasons.append(
                    "status rejected -> invalidated_at; the rejection time is not in history "
                    "(metadata-only transition, CN A.1), so the export time is used"
                )
            else:
                inval = None
            rec = record_for_version(
                node, entry, record_id=rid, supersedes=prev_id, invalidated_at=inval
            )
            records.append(rec)
            receipt.add(
                rid, "transformed", rid,
                "edited_at dropped; hashes not carried (see UNMAPPABLE)", *reasons,
            )
            prev_id = rid
    manifest = Manifest(
        source_authority="contextnest",
        source_namespace=name,
        object_kinds=["ibm-memory-record"],
        selection=selector,
        checkpoint=nest.latest_checkpoint(),
    )
    bundle = ExportBundle(
        system_id=f"contextnest:{slug_path(name)}", records=records, tag_context=TAG_CONTEXT
    )
    return bundle, manifest, receipt


# --------------------------------------------------------------------------- import


def _chains(records: list[MemoryRecord], receipt: Receipt) -> list[list[MemoryRecord]]:
    """Split records into override chains, oldest first. A record two others both
    supersede is a fork; the later branch is reported unresolved (Cognee §3.5: concurrent
    events surface as conflicts)."""
    by_id = {r.id: r for r in records}
    children: dict[str, list[MemoryRecord]] = {}
    roots = []
    for r in sorted(records, key=lambda r: (r.lifecycle.created_at, r.lifecycle.version)):
        if r.supersedes and r.supersedes in by_id:
            children.setdefault(r.supersedes, []).append(r)
        else:
            roots.append(r)
    chains = []
    for root in roots:
        chain, cur = [root], root
        while children.get(cur.id):
            first, *rest = children[cur.id]
            for fork in rest:
                receipt.add(
                    fork.origin or fork.id, "unresolved", None,
                    f"conflicting revision: {cur.id} is superseded twice",
                )
            chain.append(first)
            cur = first
        chains.append(chain)
    return chains


def _node_id_for(chain: list[MemoryRecord], system_id: str, prefix: str) -> str:
    for r in chain:
        for s in r.scope_tags:
            if s.startswith("node:"):
                return s.removeprefix("node:")
    for r in chain:
        for s in r.scope_tags:
            if s.startswith("path:"):  # the IBM prototype's Packer bridge
                rel = s.removeprefix("path:").removesuffix(".md")
                return f"{prefix}/{slug_path(system_id)}/{slug_path(rel)}"
    return f"{prefix}/{slug_path(system_id)}/{slug_path(chain[0].id)[:24]}"


def _frontmatter_for(rec: MemoryRecord, origin: str, reasons: list[str]) -> dict[str, Any]:
    def tagged(prefix: str) -> str | None:
        hits = [t.removeprefix(prefix) for t in rec.semantic_tags if t.startswith(prefix)]
        return hits[0] if hits else None

    title, ntype, desc = tagged("title:"), tagged("type:"), tagged("description:")
    if title is None:
        heading = re.search(r"^#\s+(.+)$", rec.body, re.MULTILINE)
        lines = rec.body.strip().splitlines() or ["untitled"]
        title = heading.group(1).strip() if heading else lines[0][:80]
        reasons.append("no title: tag; title taken from the body")
    if ntype not in PLAIN_TYPES:
        if ntype is not None:
            reasons.append(f"type:{ntype} needs a typed block in CN; imported as document")
        ntype = "document"
    tags = []
    for t in rec.semantic_tags:
        if t.startswith(("title:", "type:", "description:")):
            continue
        if is_cn_tag(t):
            if not t.startswith("#"):
                reasons.append(f"semantic tag {t!r} written as {as_cn_tag(t)!r}")
            tags.append(as_cn_tag(t))
        else:
            reasons.append(f"semantic tag {t!r} does not fit CN tag grammar; kept in metadata")
    other_scopes = [s for s in rec.scope_tags if not s.startswith("node:")]
    if other_scopes:
        reasons.append(f"scope tags {other_scopes} kept in metadata, not enforced by ctx")
    derived = [s for s in rec.lifecycle.source_material if s.startswith("contextnest://")]
    return {
        "title": title,
        "type": ntype,
        "tags": sorted(set(tags)) or None,
        "description": desc,
        "derived_from": derived or None,
        "metadata": {
            "omp": {
                "ibm": {
                    "origin": origin,
                    "created_at": rec.lifecycle.created_at,
                    "semantic_tags": list(rec.semantic_tags),
                    "scope_tags": list(rec.scope_tags),
                    "source_material": list(rec.lifecycle.source_material),
                    "how": rec.lifecycle.provenance.how,
                }
            }
        },
    }


def _known_identities(nest: NestIO, node_id: str) -> set[str]:
    """Identities already in this node's history: its own pinned URIs and the origins an
    earlier import recorded in version notes."""
    known: set[str] = set()
    for e in nest.history(node_id):
        if e.published_at:
            known.add(_pinned(nest, node_id, e.version))
        m = _NOTE.match(e.note or "")
        if m:
            known.add(m.group(2))
    return known


def import_bundle(
    nest: NestIO, bundle: ExportBundle, *, prefix: str = "nodes/imported"
) -> Receipt:
    """Write an IBM bundle into a nest, one node per override chain, through `ctx publish`.

    - A record whose identity is already in the node's history is not written again
      (retries and old archives do not duplicate).
    - A chain whose tip is invalidated ends with the node set to `rejected`.
    - If ctx refuses a write (for example the node is `rejected` here), the record is
      reported rejected with ctx's message and the live file is left as it was.
    """
    receipt = Receipt("import", counterpart=bundle.system_id)
    local = nest.root
    ids = {r.id for r in bundle.records}
    local_of: dict[str, str] = {}
    for chain in _chains(list(bundle.records), receipt):
        node_id = _node_id_for(chain, bundle.system_id, prefix)
        exists = (local / f"{node_id}.md").exists()
        known = _known_identities(nest, node_id) if exists else set()
        wrote_tip = False
        for i, rec in enumerate(chain):
            origin = rec.origin or f"{bundle.system_id}:{rec.id}"
            if rec.id in known or origin in known or (rec.origin and rec.origin in known):
                receipt.add(
                    origin, "accepted", f"contextnest://{node_id}",
                    "already present in this nest (same identity); not written again",
                )
                continue
            reasons: list[str] = []
            if i == 0 and rec.supersedes and rec.supersedes not in ids:
                reasons.append(
                    f"supersedes {rec.supersedes}, which is not in this bundle; "
                    "written as this node's next version here"
                )
            fm = _frontmatter_for(rec, origin, reasons)
            if i == 0 and not exists:
                fm["created_at"] = rec.lifecycle.created_at  # when the memory first existed
            if fm.get("derived_from"):
                # lineage to a record imported in this same bundle points at its local copy
                mapped = [local_of.get(d, d) for d in fm["derived_from"]]
                if mapped != fm["derived_from"]:
                    reasons.append("derived_from re-pointed to the imported revisions here")
                fm["derived_from"] = mapped
            client = {}
            if rec.lifecycle.provenance.model:
                client["model"] = rec.lifecycle.provenance.model
            if rec.lifecycle.provenance.ai_used:
                client["ai_used"] = "true"
            try:
                cp = nest.write_revision(
                    node_id,
                    body=rec.body,
                    frontmatter=fm,
                    author=rec.lifecycle.author,
                    note=f"omp-import created_at={rec.lifecycle.created_at} origin={origin}",
                    agent=rec.lifecycle.provenance.agent,
                    client=client,
                )
            except CtxError as e:  # ctx is the authority on what may be published
                receipt.add(origin, "rejected", None, f"ctx refused: {e}")
                continue
            reasons.append("created_at kept in the version note; ctx stamps its own clocks")
            local_of[rec.id] = f"contextnest://{node_id}@{cp}"
            receipt.add(origin, "transformed", local_of[rec.id], *reasons)
            wrote_tip = i == len(chain) - 1
        tip = chain[-1]
        if wrote_tip and tip.lifecycle.invalidated_at is not None:
            nest.set_status(node_id, "rejected")
            receipt.entries[-1].reasons.append(
                "tip is invalidated: node set to rejected (hidden from agents, history kept)"
            )
    return receipt
