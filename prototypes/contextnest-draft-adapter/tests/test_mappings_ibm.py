"""Context Nest <-> IBM MemoryRecord round trips, with the IBM prototype's own classes."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("ibm_memory")
pytest.importorskip("yaml")

from ibm_memory import MemoryStore, Provenance  # noqa: E402
from ibm_memory.packer_bridge import records_from_memory_dir  # noqa: E402

from mappings import ibm  # noqa: E402
from mappings._nest import NestIO, canon_body  # noqa: E402

PACKER_EXAMPLE = (
    Path(__file__).resolve().parents[2] / "packer-draft-langchain-harness" / "examples" / "memory"
)


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> NestIO:
    """A nest with an edited node, a derived node, a rejected node and a pending one."""
    if shutil.which("ctx") is None:
        pytest.skip("ctx not installed (npm install -g @promptowl/contextnest-cli)")
    nest = NestIO.init(tmp_path_factory.mktemp("cn-source"), "IBM source nest")
    nest.write_revision(
        "nodes/people/sruly",
        body="# Sruly\n\nWorks on the Open Memory Protocol. Prefers short answers.",
        frontmatter={"title": "Sruly", "type": "persona", "tags": ["#person", "#core"],
                     "description": "Who Sruly is"},
        author="alice@example.org",
        note="first write",
    )
    nest.write_revision(
        "nodes/people/sruly",
        body="# Sruly\n\nWorks on the Open Memory Protocol. Prefers short answers, by email.",
        frontmatter={},
        author="bob@example.org",
        note="added channel from a call",
        agent="call-notes",
        client={"model": "example-model"},
    )
    v1 = f"contextnest://nodes/people/sruly@{nest.checkpoint_of('nodes/people/sruly', 1)}"
    nest.write_revision(
        "nodes/notes/summary",
        body="Sruly: OMP, short answers.",
        frontmatter={"title": "Summary", "tags": ["#summary"], "derived_from": [v1]},
        author="carol@example.org",
    )
    nest.write_revision(
        "nodes/notes/old",
        body="The old meeting room was 4B.",
        frontmatter={"title": "Old room"},
        author="alice@example.org",
    )
    nest.set_status("nodes/notes/old", "rejected")
    nest.write_revision(
        "nodes/memory/pending",
        body="Sruly might move to Brooklyn.",
        frontmatter={"title": "Pending", "status": "pending_review"},
        author="agent@example.org",
        publish=False,
    )
    return nest


def _by_node(bundle):
    out: dict[str, list] = {}
    for r in bundle.records:
        node = next(s for s in r.scope_tags if s.startswith("node:")).removeprefix("node:")
        out.setdefault(node, []).append(r)
    return {k: sorted(v, key=lambda r: r.lifecycle.version) for k, v in out.items()}


# ------------------------------------------------------------------ CN -> IBM


def test_export_is_an_ibm_bundle_with_override_chains(source):
    bundle, manifest, receipt = ibm.export_bundle(source)
    chains = _by_node(bundle)
    assert set(chains) == {"nodes/people/sruly", "nodes/notes/summary", "nodes/notes/old"}

    v1, v2 = chains["nodes/people/sruly"]
    assert v1.id.startswith("contextnest://nodes/people/sruly@") and v2.supersedes == v1.id
    assert (v1.lifecycle.version, v2.lifecycle.version) == (1, 2)
    assert v1.lifecycle.invalidated_at == v2.lifecycle.created_at and v2.is_valid
    assert v1.lifecycle.author == "alice@example.org" and not v1.lifecycle.provenance.ai_used
    p = v2.lifecycle.provenance
    assert v2.lifecycle.author == "bob@example.org"
    assert p.ai_used and p.agent == "call-notes" and p.model == "example-model"
    assert p.how == "added channel from a call"
    assert "by email" in v2.body and "by email" not in v1.body
    assert {"#person", "#core", "type:persona", "title:Sruly", "description:Who Sruly is"} <= set(
        v2.semantic_tags
    )

    (summary,) = chains["nodes/notes/summary"]
    assert summary.lifecycle.source_material == [v1.id]  # the input revision itself, pinned

    (old,) = chains["nodes/notes/old"]
    assert old.lifecycle.invalidated_at is not None  # rejected -> invalidated

    omitted = [e.origin_id for e in receipt.by_outcome("omitted")]
    assert omitted == ["contextnest://nodes/memory/pending"]
    assert manifest.completeness == "snapshot" and manifest.checkpoint is not None


def test_ibm_store_accepts_the_export_as_is(source):
    bundle, _, _ = ibm.export_bundle(source)
    store = MemoryStore("ibm-side")
    store.import_bundle(bundle)
    assert any("by email" in r.body for r in store.as_of())
    assert not any("4B" in r.body for r in store.as_of())  # rejected stays invalid
    assert len(store.all()) == len(bundle.records)


def test_selection_export_only_carries_what_is_served(source):
    bundle, manifest, _ = ibm.export_bundle(source, "#core")
    assert set(_by_node(bundle)) == {"nodes/people/sruly"}
    assert manifest.completeness == "selection" and manifest.selection == "#core"


# ------------------------------------------------------------------ CN -> IBM -> CN


def test_cn_to_ibm_to_cn_round_trip(source, tmp_path):
    bundle, _, _ = ibm.export_bundle(source)
    dest = NestIO.init(tmp_path / "dest", "IBM dest nest")
    receipt = ibm.import_bundle(dest, bundle)
    assert not receipt.by_outcome("rejected") and not receipt.by_outcome("unresolved")

    for node_id in ("nodes/people/sruly", "nodes/notes/summary", "nodes/notes/old"):
        a, b = source.history(node_id), dest.history(node_id)
        assert [e.version for e in a] == [e.version for e in b], node_id
        assert [e.edited_by for e in a] == [e.edited_by for e in b], node_id
        for e in a:
            ra, rb = source.reconstruct(node_id, e.version), dest.reconstruct(node_id, e.version)
            assert canon_body(ra.body) == canon_body(rb.body)
            assert ra.title == rb.title and sorted(ra.tags) == sorted(rb.tags)
            assert ra.frontmatter.get("type", "document") == rb.frontmatter.get(
                "type", "document"
            )

    assert dest.history("nodes/people/sruly")[1].client.get("agent") == "call-notes"
    assert dest.read("nodes/notes/old").status == "rejected"
    assert "nodes/people/sruly" in dest.served("#core")
    assert "nodes/notes/old" not in dest.served("#core | #summary | type:document")
    assert not (dest.root / "nodes/memory/pending.md").exists()

    # lineage points at the imported revision in the new nest, not the old nest's checkpoint
    v1_here = f"contextnest://nodes/people/sruly@{dest.checkpoint_of('nodes/people/sruly', 1)}"
    assert dest.read("nodes/notes/summary").frontmatter["derived_from"] == [v1_here]

    assert dest.ctx.run_json("verify", "--json")["valid"] is True

    # and back out again: same chains, same bodies
    again, _, _ = ibm.export_bundle(dest)
    first, second = _by_node(bundle), _by_node(again)
    assert set(first) == set(second)
    for node_id in first:
        assert [r.body for r in first[node_id]] == [r.body for r in second[node_id]]
        assert [r.lifecycle.version for r in first[node_id]] == [
            r.lifecycle.version for r in second[node_id]
        ]


def test_importing_the_same_bundle_twice_writes_nothing_new(source, tmp_path):
    bundle, _, _ = ibm.export_bundle(source)
    dest = NestIO.init(tmp_path / "dest", "retry nest")
    ibm.import_bundle(dest, bundle)
    before = {n: len(dest.history(n)) for n in dest.ids()}
    retry = ibm.import_bundle(dest, bundle)
    assert {e.outcome for e in retry.entries} == {"accepted"}
    assert {n: len(dest.history(n)) for n in dest.ids()} == before


# ------------------------------------------------------------------ IBM prototype -> CN


def _ibm_store() -> MemoryStore:
    """Records made by the IBM prototype itself: its Packer bridge output, an override chain
    with a scope tag, an AI-written memory, and an invalidated one."""
    store = MemoryStore("ibm-proto")
    records_from_memory_dir(PACKER_EXAMPLE, store)
    boston = store.write("Lives in Boston", author="sruly", scope_tags=["user:sruly"],
                         semantic_tags=["location"])
    store.override(boston.id, "Lives in Brooklyn", author="sruly")
    store.write(
        "Sruly uses uv", author="sruly", scope_tags=["user:sruly"], semantic_tags=["tooling"],
        provenance=Provenance(ai_used=True, model="fake", agent="t", how="extracted"),
    )
    gone = store.write("Office is 4B", author="sruly", scope_tags=["team:eng"])
    store.invalidate(gone.id)
    return store


def test_ibm_prototype_records_run_on_context_nest(tmp_path):
    if shutil.which("ctx") is None:
        pytest.skip("ctx not installed")
    store = _ibm_store()
    bundle = store.export()
    nest = NestIO.init(tmp_path / "n", "from IBM")
    receipt = ibm.import_bundle(nest, bundle)
    assert not receipt.by_outcome("rejected")
    landed = receipt.identity_map
    assert len(landed) == len(bundle.records)

    # the Packer bridge's path: scope tag decides where a file-derived record lands
    human = nest.read("nodes/imported/ibm-proto/human")
    assert "Sruly, maintainer" in human.body
    assert human.frontmatter["description"] == "What I know about the person I am interacting with."

    # an override chain is one node with two versions; the current body is the override
    chain_node = next(
        n for n in nest.ids() if "Brooklyn" in nest.read(n).body
    )
    hist = nest.history(chain_node)
    assert [e.version for e in hist] == [1, 2]
    assert "Boston" in nest.reconstruct(chain_node, 1).body
    live = nest.read(chain_node)
    assert live.status == "published" and "#location" in live.tags
    assert live.omp["ibm"]["scope_tags"] == ["user:sruly"]  # kept, not enforced

    uv = next(n for n in nest.ids() if nest.read(n).body.strip() == "Sruly uses uv")
    entry = nest.history(uv)[-1]
    assert entry.client.get("agent") == "t" and entry.client.get("model") == "fake"

    office = next(n for n in nest.ids() if "4B" in nest.read(n).body)
    assert nest.read(office).status == "rejected"  # invalidated -> hidden, history kept

    assert any("scope tags" in r for e in receipt.entries for r in e.reasons)
    assert nest.ctx.run_json("verify", "--json")["valid"] is True


def test_ibm_to_cn_to_ibm_keeps_what_ibm_can_see(tmp_path):
    if shutil.which("ctx") is None:
        pytest.skip("ctx not installed")
    store = _ibm_store()
    nest = NestIO.init(tmp_path / "n", "ibm round trip")
    ibm.import_bundle(nest, store.export())
    back, _, _ = ibm.export_bundle(nest)
    other = MemoryStore("ibm-again")
    other.import_bundle(back)
    # bodies come back with one trailing newline (the exchange form, canon_body)
    assert sorted(r.body.strip() for r in other.as_of()) == sorted(
        r.body.strip() for r in store.as_of()
    )
    # scope and semantic tags come back as IBM wrote them, created_at from the version note
    by_body = {r.body.strip(): r for r in store.as_of()}
    for r in other.as_of():
        orig = by_body[r.body.strip()]
        assert set(orig.scope_tags) <= set(r.scope_tags)
        assert set(orig.semantic_tags) == set(r.semantic_tags)
        assert r.lifecycle.created_at == orig.lifecycle.created_at
