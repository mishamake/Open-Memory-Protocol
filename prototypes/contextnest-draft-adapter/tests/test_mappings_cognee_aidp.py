"""Cognee six-part core table, manifest and receipt; AIDP FMP shapes and endpoint table."""

from __future__ import annotations

import shutil

import pytest

pytest.importorskip("yaml")
pytest.importorskip("ibm_memory")
pytest.importorskip("open_memory_protocol")

from mappings import aidp, cognee, ibm, packer  # noqa: E402
from mappings._nest import NestIO  # noqa: E402

PARTS = {"identity", "evidence", "scope", "lineage", "lifecycle", "exchange"}


@pytest.fixture(scope="module")
def nest(tmp_path_factory) -> NestIO:
    if shutil.which("ctx") is None:
        pytest.skip("ctx not installed (npm install -g @promptowl/contextnest-cli)")
    n = NestIO.init(tmp_path_factory.mktemp("core"), "core nest")
    n.write_revision(
        "nodes/notes/transcript-fact",
        body="Sruly said drafts are due 2026-10-02.",
        frontmatter={"title": "Deadline", "tags": ["#project-omp"]},
        author="sruly@example.org",
    )
    cp = n.latest_checkpoint()
    n.write_revision(
        "nodes/notes/summary",
        body="OMP drafts: due 2026-10-02.",
        frontmatter={"title": "Summary", "tags": ["#project-omp"],
                     "derived_from": [f"contextnest://nodes/notes/transcript-fact@{cp}"]},
        author="reviewer@example.org",
        agent="summarizer",
        client={"model": "example-model"},
    )
    n.write_revision(
        "nodes/notes/retired",
        body="Old fact.",
        frontmatter={"title": "Retired"},
        author="sruly@example.org",
    )
    n.set_status("nodes/notes/retired", "rejected")
    return n


# ------------------------------------------------------------------ Cognee, declarative


def test_every_requirement_has_a_row_and_a_status():
    assert {r["part"] for r in cognee.SEMANTIC_CORE} == PARTS
    for row in cognee.SEMANTIC_CORE:
        assert set(row) == {"part", "requirement", "carrier", "status", "note"}
        assert row["status"] in ("carried", "partial", "proposed", "not carried")
        if row["status"] != "carried":
            assert row["note"], f"{row['requirement']}: a gap needs a reason"
    # the not-carried rows are the published UNMAPPABLE list
    assert set(cognee.UNMAPPABLE) == {
        r["requirement"] for r in cognee.SEMANTIC_CORE if r["status"] == "not carried"
    }


def test_every_mapping_lists_unmappable_fields():
    for mod in (ibm, packer, aidp):
        assert mod.UNMAPPABLE and all(mod.UNMAPPABLE.values()), mod.__name__
        for direction in mod.UNMAPPABLE.values():
            assert all(isinstance(v, str) and v for v in direction.values())


# ------------------------------------------------------------------ Cognee, per node


def test_core_view_reads_six_parts_from_ctx(nest):
    v = cognee.core_view(nest, "nodes/notes/summary")
    assert set(v) == PARTS
    assert v["identity"]["id"] == "contextnest://nodes/notes/summary"
    assert v["identity"]["revisions"][0]["chain_hash"].startswith("sha256:")
    assert v["evidence"]["role"] == "machine_derived"
    assert v["scope"]["author"] == "reviewer@example.org" and v["scope"]["agent"] == "summarizer"
    assert v["scope"]["policy"] is None
    assert v["lineage"]["inputs_pinned"] is True
    assert v["lifecycle"]["state"] == "active" and v["lifecycle"]["valid_time"] is None

    fact = cognee.core_view(nest, "nodes/notes/transcript-fact")
    assert fact["evidence"]["role"] == "human_assertion"
    assert cognee.core_view(nest, "nodes/notes/retired")["lifecycle"]["state"] == "invalidated"


def test_manifest_and_receipt(nest):
    manifest, receipt = cognee.export_manifest(nest, "#project-omp")
    m = manifest.to_json()
    assert m["completeness"] == "selection" and m["selection"] == "#project-omp"
    assert m["source_authority"] == "contextnest" and m["checkpoint"] is not None
    assert {e.origin_id for e in receipt.entries} == {
        "contextnest://nodes/notes/transcript-fact",
        "contextnest://nodes/notes/summary",
    }
    assert all(e.outcome == "transformed" and e.reasons for e in receipt.entries)
    snap, full = cognee.export_manifest(nest)
    assert snap.completeness == "snapshot"
    retired = next(e for e in full.entries if e.origin_id.endswith("retired"))
    assert any("rejected" in r for r in retired.reasons)
    assert receipt.to_json()["counts"] == {"transformed": 2}


# ------------------------------------------------------------------ AIDP / FMP


def test_nodes_map_to_fmp_files_and_inferences(nest):
    out = aidp.export_fmp(nest, "#project-omp")
    assert [f["name"] for f in out["files"]] == ["nodes/notes/transcript-fact.md"]
    (inf,) = out["inferences"]
    assert inf["created_by"] == {"kind": "agent", "name": "summarizer", "model": "example-model"}
    assert inf["based_on"][0].startswith("contextnest://nodes/notes/transcript-fact@")
    assert inf["metadata"]["contextnest"]["uri"] == "contextnest://nodes/notes/summary"

    schema = pytest.importorskip("fmp.schema")
    schema.FileUpload.model_validate(out["files"][0])
    schema.InferenceUpload.model_validate(inf)


def test_fmp_inference_upload_waits_for_review(nest):
    node_id = aidp.upload_inference(
        nest,
        {"content": "Sruly prefers chat for short questions.",
         "created_by": {"kind": "agent", "name": "fmp-agent", "model": "m"},
         "based_on": ["transcript:t9#2"]},
    )
    assert nest.read(node_id).status == "pending_review"
    assert node_id not in nest.served("type:document")


def test_endpoint_table_covers_every_fmp_endpoint():
    names = {e["endpoint"] for e in aidp.FMP_ENDPOINTS}
    assert names == {
        "/fmp/info", "/fmp/upload/files", "/fmp/upload/transcript", "/fmp/upload/inferences",
        "/fmp/search", "/fmp/read_transcripts", "/fmp/read_inferences", "/fmp/delete",
    }
