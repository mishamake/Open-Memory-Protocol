# Context Nest cross-draft mappings

How a Context Nest node, vault and history line up with the other OMP drafts, field by
field, and what does not line up. Each table has a code counterpart in this folder and a
test in `../tests/`. Every module also exports an `UNMAPPABLE` dict with the same content as
the "Does not map" lists below, so a tool can read it.

The drafts:

- IBM draft v0.1 (Gabe Goodhart and IBM): memory records, immutability, import/export.
- Packer draft v0.2 (Charles Packer, Letta): Markdown directory loading profile.
- Cognee draft v0.1 (Vasilije Markovic and the Cognee team): six-part semantic core.
- AIDP draft v0.1 (Sruly Rosenblat, AI Disclosures Project): Federated Memory Protocol.

**One rule for all of them.** Version numbers, content and chain hashes, checkpoints,
reconstruction and status transitions come from the `ctx` CLI. A mapping writes a node as a
Markdown file and then runs `ctx publish`; it reads an old revision with `ctx reconstruct`
and a point in time from `ctx checkpoint list`. The Python here only moves fields between
shapes.

## IBM MemoryRecord (`ibm.py`)

Uses the IBM prototype's own `MemoryRecord`, `Lifecycle`, `Provenance` and `ExportBundle`.
Both drafts refuse in-place edits, so one node with N published versions is one IBM override
chain of N records, and back.

| Context Nest | IBM record | Direction notes |
|---|---|---|
| one published version | one `MemoryRecord` | drafts, pending and approved revisions are not records (receipt: omitted) |
| `contextnest://<id>@<checkpoint>` | `id` | the pinned URI of that version; unique and resolvable |
| body at that version (`ctx reconstruct`) | `body` | exchanged with one trailing newline |
| history `edited_by` | `lifecycle.author` | |
| history `client.agent`, `client.model`, `note` | `lifecycle.provenance` (`agent`, `model`, `how`); `ai_used` when an agent or model is present | import passes them back as `--agent`, `--client model=` |
| history `published_at` | `lifecycle.created_at` | an imported version keeps the IBM instant in its note and gives it back |
| next version's `published_at` | `lifecycle.invalidated_at` of the superseded record | |
| `status: rejected` on the tip | `lifecycle.invalidated_at` of the tip | import sets `rejected` when the tip is invalidated |
| `version` | `lifecycle.version` | integer comparator in both |
| `derived_from` | `lifecycle.source_material` | import re-points lineage to records imported in the same bundle |
| previous version's pinned URI | `supersedes` | |
| `tags`, `type`, `title`, `description` | `semantic_tags`: `#x`, `type:x`, `title:x`, `description:x` | same prefix style as the IBM prototype's Packer bridge |
| node id | scope tag `node:<id>` | same idea as the bridge's `path:` tag |
| `metadata.omp.ibm` | IBM fields with no CN key (scope tags, raw semantic tags, source material, origin) | kept so IBM to CN to IBM gives them back |

Does not map, CN to IBM:
- approval states other than published and rejected; unpublished revisions are omitted
- `edited_at` (IBM has one creation clock)
- the checkpoint as whole-nest state (only inside `id` as `@N`)
- `content_hash`, `chain_hash`, `checksum` (a receiver cannot verify; a re-import gets new hashes from ctx)
- in-prose links (stay in the body), packs and selectors (recorded in the manifest)
- when a `published -> rejected` transition happened (metadata-only, CN A.1; export time is used and the receipt says so)
- `client.session_id` and custom client keys

Does not map, IBM to CN:
- scope tags: CN leaves read permission out (CN draft §1). Kept under `metadata.omp.ibm.scope_tags`, not enforced. Retained, not understood.
- `ScopePolicy` ACLs (not in a bundle)
- `created_at` per revision (ctx stamps its own; the original is in the version note)
- `invalidated_at` of a superseded record (the next version implies it; the instant is not kept)
- semantic tags outside the CN tag grammar (kept in metadata only)
- `Delete`: the importer never deletes; absence from a bundle is not deletion

## Packer directory (`packer.py`)

Checked with the `python-loader-validator` (`validate_memory`, `load_memory`).

| Context Nest | Packer directory |
|---|---|
| nodes the core selector serves (default `pack:core`) | root-level files, always loaded |
| every other published node | deferred file at `<node id>.md` |
| `description`, else `title` | `description` front matter |
| `tags` | `tags: a, b` (no `#`, which starts a YAML comment) |
| uri, version, status, type, checksum, derived_from | `metadata: {"contextnest": {...}}`, values read from ctx |
| floating `contextnest://` links to exported nodes | relative links |
| folders | directories, each with a `MEMORY.md` (generated where the nest has none) |
| `metadata.omp.packer_path` | the file's original path, so Packer to CN to Packer puts it back |
| `#core` tag and `packs/core.yml` (written on import) | the root tier |

Does not map, CN to Packer: version history, hashes and checkpoints (one point in time;
version and checksum travel in metadata); non-published nodes; selectors other than the core
one; `type` and `derived_from` (metadata only); pinned `@N` links; wikilinks (left as
written).

Does not map, Packer to CN: file names and load order (a node id is the slugged path;
root files become `#core`); the free-form `metadata` field (kept, not interpreted); who may
write a file (out of scope in both drafts).

## Cognee six-part core (`cognee.py`)

A declarative table, `SEMANTIC_CORE`, one row per requirement in Cognee §3. Condensed:

| Part | Context Nest carrier | Status |
|---|---|---|
| Identity and revision | path + `version` + `chain_hash`; `id@checkpoint`; origin mapping in metadata | carried, origin mapping partial |
| Content, origin, evidence | `type`, `client.agent`, `derived_from` read as a role (`evidence_role()`) | partial: no transcript type |
| Scope, ownership, authority | `edited_by`, `client.agent`, optional `author` | partial; portable policy not carried |
| Provenance and lineage | `derived_from` with pinned URIs; history `edited_by`, `edited_at`, `note`, `client` | carried; no PROV output |
| Time, lifecycle, deletion | `published_at`, `edited_at`, checkpoints, `rejected`; `forgotten` and tombstones proposed (CN §6.3) | partial; no valid time; forget proposed |
| Exchange capability, fidelity | directory copy + `ctx verify`; `exchange.Manifest` and `exchange.Receipt` from these mappings | partial |

`core_view(nest, id)` gives one node's six parts, read from ctx. `export_manifest(nest,
selector)` returns a manifest (authority, namespace, kinds, snapshot or selection, checkpoint)
and a receipt with accepted, transformed, omitted, unresolved and rejected entries and their
reasons. COGX is Cognee's format; nothing here reads or writes it or imports cognee.

Not carried: portable policy (principals, actions, retention); W3C PROV output.

## AIDP / FMP (`aidp.py`)

| Context Nest | FMP |
|---|---|
| node written by a person, no `derived_from` | `file`: `name`, `content`, `mime: text/markdown`, `metadata` |
| node written by an agent, or with `derived_from` | `inference`: `content`, `date`, `created_by`, `based_on`, `metadata` |
| `published_at` | `date` |
| `edited_by`, `client.agent`, `client.model` | `created_by` (`kind`, `name`, `model`) |
| `derived_from` | `based_on` |
| uri, version, status, checksum, tags, type, evidence role | `metadata.contextnest` |
| `upload_inference()` | writes a `pending_review` node; served only after a person publishes |

Which `/fmp` endpoints a Context Nest server (ctx, or the CN MCP server) could expose:

| Endpoint | Context Nest | Fit |
|---|---|---|
| `/fmp/info` | `ctx info --json` / `context_init` | direct |
| `/fmp/upload/files` | create and publish a node; PDFs via `context_import_pdf` | direct |
| `/fmp/upload/transcript` | no transcript type | gap |
| `/fmp/upload/inferences` | `pending_review` node (the adapter's `nest_propose`) | direct, with a review gate |
| `/fmp/search` | `ctx search` / `context_search`; `ctx query` returns a set instead | direct |
| `/fmp/read_transcripts` | none | gap |
| `/fmp/read_inferences` | `ctx list` / `context_list`, filtered by evidence role | partial: no cursor |
| `/fmp/delete` | `ctx delete` (node and history); `rejected` or the proposed forget are gentler | direct, with a choice |

Does not map, CN to FMP: version history, checkpoints, hashes (version and checksum in
metadata only); non-published nodes; selectors and packs; in-prose links.
Does not map, FMP to CN: transcripts; `created_by.kind: memory_provider` (recorded as the
agent); search scores.
