"""Context Nest <-> Packer memory directory, checked by the python-loader-validator."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("open_memory_protocol")
pytest.importorskip("yaml")

from open_memory_protocol import load_memory, validate_memory  # noqa: E402
from open_memory_protocol.loader import build_harness_context  # noqa: E402

from mappings import packer  # noqa: E402
from mappings._nest import NestIO, canon_body, split_frontmatter  # noqa: E402

SEED = Path(__file__).resolve().parents[1] / "examples" / "seed-nest.sh"
PACKER_EXAMPLE = (
    Path(__file__).resolve().parents[2] / "packer-draft-langchain-harness" / "examples" / "memory"
)


@pytest.fixture
def seeded(tmp_path) -> NestIO:
    """The adapter's example nest (seed-nest.sh), plus a link and a node still in review."""
    if shutil.which("ctx") is None:
        pytest.skip("ctx not installed (npm install -g @promptowl/contextnest-cli)")
    d = tmp_path / "nest"
    subprocess.run(["sh", str(SEED), str(d)], check=True, capture_output=True)
    nest = NestIO(d)
    nest.write_revision(
        "nodes/projects/omp-links",
        body="Areas are listed in [OMP areas](contextnest://nodes/projects/omp-areas).",
        frontmatter={"title": "OMP links", "tags": ["#project-omp"],
                     "description": "Where the OMP areas note is"},
        author="alice@example.org",
    )
    nest.write_revision(
        "nodes/memory/unreviewed",
        body="Deadline moved to 10-20.",
        frontmatter={"title": "Unreviewed", "status": "pending_review"},
        author="agent@example.org",
        publish=False,
    )
    return nest


def test_nest_exports_as_a_valid_packer_memory(seeded, tmp_path):
    out = tmp_path / "memory"
    _written, receipt = packer.export_packer(seeded, out)  # validates, or raises
    validate_memory(out)
    mem = load_memory(out)

    # pack:core is the root tier: always loaded
    core = sorted(f.relative_path.as_posix() for f in mem.core_files)
    assert core == ["MEMORY.md", "omp.md", "sruly.md"]
    # everything else is deferred, at its node path
    deferred = {f.relative_path.as_posix() for f in mem.external_files}
    assert {"nodes/projects/omp-areas.md", "nodes/notes/old-deadline.md",
            "nodes/projects/omp-links.md"} <= deferred
    assert "nodes/projects/MEMORY.md" in deferred and "nodes/notes/MEMORY.md" in deferred

    # front matter: description, tags without '#', ctx's own version and checksum
    fm, body = split_frontmatter((out / "sruly.md").read_text())
    assert fm["description"] == "Sruly"
    assert fm["tags"] == "person, core" or set(fm["tags"].split(", ")) == {"person", "core"}
    cn = fm["metadata"]["contextnest"]
    assert cn["uri"] == "contextnest://nodes/people/sruly" and cn["version"] >= 1
    assert cn["checksum"].startswith("sha256:") and cn["type"] == "persona"
    assert "Prefers short answers." in body

    # a floating link becomes a relative path the Packer harness can read
    links = (out / "nodes/projects/omp-links.md").read_text()
    assert "](omp-areas.md)" in links

    # the root index surfaces deferred material (Packer rule 3)
    ctx_for_agent = build_harness_context(mem)
    assert "nodes/" in ctx_for_agent.core_context
    assert Path("nodes/projects/omp-areas.md") in ctx_for_agent.deferred_index

    # a node in review never reaches a Packer harness, and the receipt says so
    assert not (out / "nodes/memory/unreviewed.md").exists()
    assert "contextnest://nodes/memory/unreviewed" in [
        e.origin_id for e in receipt.by_outcome("omitted")
    ]


def test_packer_export_reads_through_the_ibm_bridge(seeded, tmp_path):
    """CN -> Packer -> IBM: the IBM prototype's own bridge reads what we wrote."""
    pytest.importorskip("ibm_memory")
    from ibm_memory import MemoryStore
    from ibm_memory.packer_bridge import records_from_memory_dir

    out = tmp_path / "memory"
    packer.export_packer(seeded, out)
    recs = records_from_memory_dir(out, MemoryStore("via-packer"))
    by_path = {next(s for s in r.scope_tags if s.startswith("path:")): r for r in recs}
    sruly = by_path["path:sruly.md"]
    assert "tier:core" in sruly.scope_tags
    assert {"person", "core", "description:Sruly"} <= set(sruly.semantic_tags)
    assert "tier:deferred" in by_path["path:nodes/projects/omp-areas.md"].scope_tags


def test_packer_directory_round_trips_through_a_nest(tmp_path):
    """Packer -> CN -> Packer: every file returns to its path with its body and description,
    root files are still the root tier, and the result validates."""
    if shutil.which("ctx") is None:
        pytest.skip("ctx not installed")
    nest = NestIO.init(tmp_path / "nest", "packer round trip")
    receipt = packer.import_packer(nest, PACKER_EXAMPLE)
    assert not receipt.by_outcome("rejected")
    assert set(nest.served("pack:core")) == {
        "nodes/memory", "nodes/persona", "nodes/human",
    }
    assert nest.ctx.run_json("verify", "--json")["valid"] is True

    out = tmp_path / "out"
    packer.export_packer(nest, out)
    src = {p.relative_to(PACKER_EXAMPLE).as_posix() for p in PACKER_EXAMPLE.rglob("*.md")}
    got = {p.relative_to(out).as_posix() for p in out.rglob("*.md")}
    assert got == src
    for rel in src:
        a_fm, a_body = split_frontmatter((PACKER_EXAMPLE / rel).read_text())
        b_fm, b_body = split_frontmatter((out / rel).read_text())
        assert canon_body(a_body) == canon_body(b_body), rel
        assert a_fm.get("description") == b_fm.get("description"), rel
    assert sorted(f.relative_path.as_posix() for f in load_memory(out).core_files) == sorted(
        f.relative_path.as_posix() for f in load_memory(PACKER_EXAMPLE).core_files
    )
