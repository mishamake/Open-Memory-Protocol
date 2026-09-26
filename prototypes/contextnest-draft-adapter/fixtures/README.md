# Shared lifecycle fixtures

Engine-neutral test cases for the lifecycle behaviour several drafts describe. A fixture
names objects, revisions and steps; it never names a file path, a record id, a node id or an
engine. Any memory system can run one by mapping the steps to its own operations and
answering the questions under `expect`.

The Cognee draft (§6) asks for public fixtures that two independent implementations exchange
both ways, including "an old archive attempting to reintroduce a tombstoned revision". These
are offered as a start on that.

| Fixture | Case | Drafts it exercises |
|---|---|---|
| `correction.json` | a later statement supersedes an earlier one (Cognee's Tuesday to Friday example) | Cognee §3.1, §3.5; IBM override; CN §6.1 |
| `consolidation.json` | a summary names every input revision, and keeps naming them after an input is corrected | Cognee §3.4; IBM source material; CN `derived_from` |
| `invalidation.json` | an invalidated memory leaves current reads; an archive taken before the invalidation is imported again | Cognee §3.5, §3.6; IBM invalidate and import; CN A.1 `rejected` |
| `pinned-read.json` | reads pinned after step N see one consistent state of every memory | Cognee §3.5; IBM recall timestamp; CN §5.1 checkpoints |
| `resurrection.json` | a forgotten memory, an old export imported again: not current, reported as forgotten, summary flagged, verification passes | Cognee §3.5, §6; CN §6.3 forget (proposed) |

## Format

```json
{
  "fixture": "correction",
  "title": "...", "about": "...",
  "drafts": {"cognee": "...", "ibm": "...", "contextnest": "..."},
  "requires": ["supersede", "as_of"],
  "events": [{"seq": 1, "op": "assert", "object": "status-day", "revision": "r1", "body": "...",
              "actor": "sruly@example.org", "role": "human_assertion", "evidence": ["transcript:t1#4"]}],
  "expect": {"current": {"status-day": "r2"}, "history": {"status-day": ["r1", "r2"]},
             "as_of": [{"after_seq": 1, "object": "status-day", "revision": "r1"}]}
}
```

Operations, applied in `seq` order:

| `op` | Meaning |
|---|---|
| `assert` | first revision of a new object |
| `supersede` | next revision of an object; `replaces` names the revision it corrects |
| `consolidate` | first revision of a new object derived from the revisions in `inputs` |
| `invalidate` | the object stops being current; its history stays |
| `archive` | take an export of everything now, under `label` |
| `reimport` | import the archive `label` back into the same system |
| `forget` | erase the object's content (`reason_code` from CN §6.3.1), keep a tombstone |

Questions under `expect`:

| Key | Question |
|---|---|
| `current` | which revision of each object is current after the last step (`null`: none) |
| `history` | the object's revisions, oldest first |
| `as_of` | which revision was current right after step `after_seq` (`null`: none yet) |
| `lineage` | which input revisions a derived revision names |
| `reimport` | after the reimport, revisions in `not_current` must not be current |
| `forgotten`, `review_required`, `verify_passes` | forget-specific: a read says "forgotten" (not "never existed"), derived objects are flagged for review, integrity verification still passes |

`role` is the Cognee §3.2 evidence role of the revision (`human_assertion`,
`machine_derived`, ...). `evidence` is opaque source references.

## Running them

`../tests/test_fixtures.py` runs every fixture on two engines that share no code:

- the IBM prototype's `MemoryStore` (`prototypes/ibm-draft-memory-records`), and
- a real nest through `ctx`, with archives exchanged as IBM bundles by `mappings.ibm`.

Expected results, and why (the test run is what counts):

| Fixture | ctx | IBM prototype |
|---|---|---|
| correction | pass | pass |
| consolidation | pass | pass |
| pinned-read | pass | pass |
| invalidation | pass: the archive's revisions are recognised by identity and nothing is written; ctx also refuses a direct republish of a rejected node | expected failure: an import is a new memory in the receiving system (IBM draft), so the archived copy is current again. The draft does not ask importers to check what they hold; this is the case Cognee §3.5 raises. |
| resurrection | skipped until `ctx forget` ships (CN §6.3 is proposed and being built) | skipped: the IBM draft has Delete but no tombstone |


