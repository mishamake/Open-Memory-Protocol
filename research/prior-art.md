# Prior Art

Existing specifications, formats, implementations, and papers relevant to
portable agent memory. Collected so the Initiative can build on what exists and
credit the people who got there first.

This is a working index, not an endorsement or a ranking. Entries are grouped by
what they contribute and **listed alphabetically within each group**. Additions
welcome by PR; the only bar is that the work is public and someone can read it.

## Memory and context formats

**Agent Plugins specification**
`agent-plugins.org/specification`

**cognee CogX exchange format**
`docs.cognee.ai/core-concepts/further-concepts/cogx`
JSON manifest covering documents, episodes, entities, facts, memory blocks and
raw notes, scoped by user, agent, session and run ID. Related: **node sets**
(`docs.cognee.ai/core-concepts/further-concepts/node-sets`), named subgraphs used
to bound what a given query can reach.

**Context Nest Specification** (PromptOwl)
`github.com/PromptOwl/context-nest-spec` · Apache-2.0
Markdown nodes with YAML front matter. Typed nodes, a status lifecycle where only
`published` is visible to an agent and drafts are invisible by default, plus
per-node `version` and SHA-256 `checksum`. Edges come from wikilink syntax in the
prose and from a `contextnest://path[#anchor][@checkpoint]` URI scheme, indexed
into a generated `context.yaml`. Covers nine areas: document format, selector
grammar, context packs, addressable context via URI, indexing, version history,
checkpoints, context injection, and validation, with defined extension points.
Versioning uses keyframes plus diffs, immutable checkpoints over the whole graph,
and a hash chain across both document versions and checkpoints.

**me.md** (Block / goose)
Already referenced in this repository's README. Listed here for completeness.

## Trajectory and trace formats

**Harbor trajectory format**
`harborframework.com/docs/agents/trajectory-format`

**letta-ai/trajectory** (Letta)
`github.com/letta-ai/trajectory`

Both were raised around the open question of whether a memory specification
should include a trajectory specification as a subset, or reference one
maintained separately.

## Portability and cryptographic verification

**Data Transfer Initiative**
`dtinit.org` · Consumer-facing data portability. Noted as already in contact with
the Initiative.

**Portable Agent Memory** (Santhosh Kumar Ravindran)
`github.com/santhoshravindran7/portable-agent-memory` · `arxiv.org/abs/2605.11032`
"A Protocol for Cryptographically-Verified Memory Transfer Across Heterogeneous
AI Agents" (May 2026). Five-component memory model: episodic, semantic,
procedural, working, identity. Content-addressed entries with BLAKE3, linked in a
Merkle-DAG for tamper evidence, signed with Ed25519 so an importing agent can
verify provenance and reject tampered memories. Capability-scoped access tokens,
injection-resistant rehydration, JSON/CBOR serialization. Demonstrates transfer
across GPT-4, Claude, Gemini and Llama.

**ContextNest: Verifiable Context Governance for Autonomous AI Agents**
`arxiv.org/abs/2607.02116` (July 2026) · Sulpovar, Konsynski, Kanchwala, Goodhart et al.,
with IBM Research and Emory University.
Formalizes context governance as a layer beneath retrieval rather than a
replacement for it: determining which artifacts are approved, current,
attributable and integrity-verified before a retrieval system operates over them.
Combines typed Markdown with metadata, deterministic set-algebraic selectors,
`contextnest://` URI references, SHA-256 hash-chained version histories,
graph-level checkpoints, source nodes for live data over MCP, and audit traces of
agent context consumption.

Includes two controlled experiments, which may be of interest given the
evaluation discussion:

- **Stale-version attack**, isolating governance failure from retrieval failure.
  Governed selection Pareto-dominates BM25 sparse retrieval: 97% answer-quality
  pass rate versus 93-90%, at roughly one third the input-token cost.
- **Retrieval determinism**, over a 1,060-document corpus. Deterministic
  selectors and BM25 return stable document sets across repeated identical
  queries (Jaccard 1.0), while a dense + HNSW baseline is non-deterministic on
  **80% of queries** (mean Jaccard 0.611, worst case 0.210).

The second result bears on any part of the protocol that depends on replaying
what an agent saw: a seed set that shifts between runs cannot be reconstructed
after the fact.

## Memory architecture and retrieval

**Zep / Graphiti**
`arxiv.org/abs/2501.13956`, "Zep: A Temporal Knowledge Graph Architecture for Agent
Memory." Graphiti is the open-source engine. Bi-temporal: every edge carries
validity time separately from ingestion time, so "when it was true" and "when we
learned it" stay distinguishable.

**MemGPT** (Packer et al.)
`arxiv.org/abs/2310.08560` · Virtual context management and the memory-tiers-as-OS analogy
that much of the current vocabulary descends from.

**Procedural Graphs: Self-Evolving Execution Structures for LLM Agents**
`huggingface.co/papers/2609.09153` · Google DeepMind. Memory-adjacent rather than
a memory format, included as an example of relevant work from the large labs.

## Implementations

Running code that already does some part of this. Licenses are stated where they
have been verified; omissions mean unverified, not unlicensed.

**cognee**
`github.com/topoteretes/cognee` · Open source. Pipeline turning raw data into
knowledge graphs; also ships the CogX exchange format above.

**ContextNest engine and MCP server** (PromptOwl)
`github.com/PromptOwl/ContextNest` · AGPL-3.0 (copyleft)
Reference implementation of the Context Nest Specification. The engine handles
selector resolution, attribute-based eligibility, policy transforms and bundle
assembly; the MCP server is the agent-facing surface. A CLI (`ctx`) wraps the
same engine and is mainly how our own team drives a vault day to day, so it is
the easiest way to poke at the format if anyone wants to. Note the license here
is copyleft, in contrast to the Apache-2.0 specification.

**goose** (Block)
`github.com/block/goose` · Open source agent harness. Offered in the first
meeting as a candidate reference implementation for whatever this group produces.

**Honcho** (Plastic Labs)
`github.com/plastic-labs/honcho` · Open source, self-hostable memory
infrastructure oriented around user identity and personalization.

**Letta**
`github.com/letta-ai/letta` · Agent framework with versioned context
repositories, where memory changes are git-backed and auto-committed.

**Portable Agent Memory SDK**
`github.com/santhoshravindran7/portable-agent-memory` · Apache-2.0 Python SDK for
the protocol described above.

This repository's own `prototypes/` directory and experimental Python
implementation belong in this category too.

## Evaluation

**Agent Memory System Card** (Mila / Mozilla)
Already referenced in this repository's README. Self-describing memory systems
with axes including privacy, performance and efficiency, plus benchmarks for
retrieval, recall and compaction behavior. Not public at time of writing.

Evaluation came up repeatedly in the first meeting as an area with broad interest
and no owner: whether a memory system makes an agent measurably better, and the
related problem of retrieving the context appropriate to the task rather than
everything associated with the user.

---

*Additions: open a PR against this file. Please include a link, one or two
sentences on what the work contributes, and where it differs from what is already
listed. Entries do not need to agree with each other.*
