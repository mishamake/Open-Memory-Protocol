"""Context Nest node  <->  FMP `files` / `inferences` (AIDP draft v0.1, Sruly Rosenblat).

FMP splits memory by how it came to be: ground truth (files, not touched by a model before
it was saved), transcripts, and inferences (content, date, how it was made, what it is based
on, and a nested metadata object). The shapes here follow the field names the FMP prototype
proposes (prototypes/aidp-draft-fmp, `fmp.schema`), as plain dicts, so this package does not
need FastAPI to produce them. The tests validate them against `fmp.schema` when it is
installed.

    CN                                          FMP
    node written by a person, no derived_from   file  {name, content, mime, metadata}
    node written by an agent, or derived_from   inference {content, date, created_by,
                                                            based_on, metadata}
    body                                        content
    published_at of the live version            date (inference) / metadata (file)
    edited_by, client.agent, client.model       created_by {kind, name, model}
    derived_from                                based_on
    uri, version, status, checksum, tags, type  metadata.contextnest
    agent writes                                upload/inferences -> pending_review node
                                                (served only after a person publishes it)
"""

from __future__ import annotations

from typing import Any

from mappings._nest import NestIO, Node, VersionEntry, canon_body, iso, slug_path
from mappings.cognee import evidence_role

# Which /fmp endpoints a Context Nest server (ctx or the CN MCP server) could expose, and how.
FMP_ENDPOINTS: list[dict[str, str]] = [
    {"endpoint": "/fmp/info", "cn": "nest name, description, counts (ctx info --json; MCP "
     "context_init)", "fit": "direct"},
    {"endpoint": "/fmp/upload/files", "cn": "new node, written by a person, published "
     "(ctx add / context_create); PDFs through context_import_pdf", "fit": "direct"},
    {"endpoint": "/fmp/upload/transcript", "cn": "no transcript type; a transcript could be "
     "a document node with metadata.fmp.messages, or stay out of the nest", "fit": "gap"},
    {"endpoint": "/fmp/upload/inferences", "cn": "node written as pending_review (the "
     "adapter's nest_propose); not served until a person publishes it", "fit": "direct, "
     "with a review gate FMP does not have"},
    {"endpoint": "/fmp/search", "cn": "ctx search / context_search (ranked within one nest); "
     "a selector (ctx query) returns a set instead of scores", "fit": "direct"},
    {"endpoint": "/fmp/read_transcripts", "cn": "none (no transcript type)", "fit": "gap"},
    {"endpoint": "/fmp/read_inferences", "cn": "ctx list / context_list, filtered to nodes "
     "whose evidence role is derived (paging by limit)", "fit": "partial: no cursor"},
    {"endpoint": "/fmp/delete", "cn": "ctx delete removes the node and its history; "
     "rejected (hide, keep history) or the proposed forget (CN §6.3) are closer to what "
     "users usually mean", "fit": "direct, with a choice FMP does not make"},
]

UNMAPPABLE: dict[str, dict[str, str]] = {
    "cn_to_fmp": {
        "version history, checkpoints, hashes": "FMP records are flat. Version and checksum "
        "travel in metadata.contextnest; earlier versions do not.",
        "status other than published": "FMP has no approval state. Only published nodes "
        "are mapped; a pending node is not an inference yet.",
        "selectors and packs": "FMP search is a query string plus type filter.",
        "in-prose links": "Left in content; FMP has no edge type.",
    },
    "fmp_to_cn": {
        "transcripts": "No CN node type. A transcript would be stored as a document or kept "
        "out of the nest.",
        "created_by.kind == memory_provider": "CN has edited_by and client.agent; a provider "
        "model is recorded as the agent.",
        "search scores": "Not stored; scores are only comparable inside one server.",
    },
}


def node_to_fmp(node: Node, entry: VersionEntry | None) -> tuple[str, dict[str, Any]]:
    """One published node as ("file", FileUpload-shaped dict) or ("inference", ...)."""
    derived = [str(d) for d in node.frontmatter.get("derived_from") or []]
    role = evidence_role(str(node.frontmatter.get("type", "document")), entry, derived)
    meta = {
        "contextnest": {
            "uri": node.uri,
            "version": node.version,
            "status": node.status,
            "type": node.frontmatter.get("type", "document"),
            "tags": node.tags,
            "title": node.title,
            "checksum": node.frontmatter.get("checksum"),
            "evidence_role": role,
            "edited_by": entry.edited_by if entry else None,
            "published_at": entry.published_at if entry else None,
        }
    }
    if role in ("human_assertion", "source_artifact_reference"):
        return "file", {
            "name": f"{node.id}.md",
            "content": canon_body(node.body),
            "mime": "text/markdown",
            "metadata": meta,
        }
    agent = entry.client.get("agent") if entry else None
    return "inference", {
        "content": canon_body(node.body),
        "date": iso(entry.published_at if entry else node.frontmatter.get("updated_at")),
        "created_by": {
            "kind": "agent" if agent else "user",
            "name": agent or (entry.edited_by if entry else None),
            "model": entry.client.get("model") if entry else None,
        },
        "based_on": derived,
        "metadata": meta,
    }


def export_fmp(nest: NestIO, selector: str = "type:document") -> dict[str, list[dict[str, Any]]]:
    """Published nodes a selector names, split into FMP `files` and `inferences`."""
    out: dict[str, list[dict[str, Any]]] = {"files": [], "inferences": []}
    for node_id in nest.served(selector):
        node = nest.read(node_id)
        published = [e for e in nest.history(node_id) if e.published_at]
        kind, payload = node_to_fmp(node, published[-1] if published else None)
        out["files" if kind == "file" else "inferences"].append(payload)
    return out


def upload_inference(
    nest: NestIO, inference: dict[str, Any], *, folder: str = "nodes/memory"
) -> str:
    """/fmp/upload/inferences on a nest: the inference becomes a `pending_review` node that
    the resolver will not serve until a person publishes it. Returns the node id."""
    content = str(inference["content"])
    first = content.strip().splitlines()[0] if content.strip() else "inference"
    node_id = f"{folder}/{slug_path(first)[:60]}"
    by = inference.get("created_by") or {}
    nest.write_revision(
        node_id,
        body=content,
        frontmatter={
            "title": first.lstrip("# ")[:120],
            "type": "document",
            "status": "pending_review",
            "derived_from": [b for b in inference.get("based_on") or [] if "://" in b] or None,
            "metadata": {"omp": {"fmp": {
                "date": inference.get("date"),
                "created_by": by,
                "based_on": list(inference.get("based_on") or []),
                "metadata": inference.get("metadata") or {},
            }}},
        },
        author=str(by.get("name") or "fmp-client"),
        publish=False,
    )
    return node_id
