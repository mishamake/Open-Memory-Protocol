"""The shared fixtures (../fixtures/*.json) on two engines: the IBM prototype and ctx."""

from __future__ import annotations

import shutil

import pytest

pytest.importorskip("ibm_memory")
pytest.importorskip("yaml")

from fixture_drivers import CNDriver, IBMDriver, Unsupported, load_fixtures  # noqa: E402

FIXTURES = load_fixtures()

IBM_REIMPORT = (
    "IBM draft v0.1: an import becomes a new memory in the receiving system, so an archive "
    "taken before the invalidation makes the memory current again. The draft does not ask an "
    "importer to check what the system already holds; this is the case Cognee §3.5 raises."
)


def _driver(kind: str, tmp_path):
    if kind == "cn":
        if shutil.which("ctx") is None:
            pytest.skip("ctx not installed (npm install -g @promptowl/contextnest-cli)")
        return CNDriver(tmp_path)
    return IBMDriver(tmp_path)


def _check(fx: dict, d) -> list[tuple[str, str]]:
    exp = fx["expect"]
    fails: list[tuple[str, str]] = []
    for obj, want in exp.get("current", {}).items():
        got = d.current_labels(obj)
        if (want is None and got) or (want is not None and got != [want]):
            fails.append(("current", f"{obj}: want {want}, got {got}"))
    for obj, want in exp.get("history", {}).items():
        if d.history(obj) != want:
            fails.append(("history", f"{obj}: want {want}, got {d.history(obj)}"))
    for a in exp.get("as_of", []):
        got = d.as_of(a["after_seq"], a["object"])
        if got != a["revision"]:
            fails.append(("as_of", f"{a}: got {got}"))
    for rev, want in exp.get("lineage", {}).items():
        if d.lineage(rev) != sorted(want):
            fails.append(("lineage", f"{rev}: want {want}, got {d.lineage(rev)}"))
    for _label, rules in exp.get("reimport", {}).items():
        for rev in rules.get("not_current", []):
            obj = next(e["object"] for e in fx["events"] if e.get("revision") == rev)
            if rev in d.current_labels(obj):
                fails.append(("reimport", f"{rev} is current again after the reimport"))
    if isinstance(d, CNDriver):
        for obj in exp.get("forgotten", []):
            if not d.is_forgotten(obj):
                fails.append(("forgotten", obj))
        for obj in exp.get("review_required", []):
            if not d.review_required(obj):
                fails.append(("review_required", obj))
        if exp.get("verify_passes") and not d.verify_passes():
            fails.append(("verify", "ctx verify failed"))
    return fails


@pytest.mark.parametrize("engine", ["cn", "ibm"])
@pytest.mark.parametrize("fx", FIXTURES, ids=[f["fixture"] for f in FIXTURES])
def test_fixture(fx, engine, tmp_path):
    d = _driver(engine, tmp_path)
    for need in fx.get("requires", []):
        if need in d.missing:
            pytest.skip(f"{d.name}: {d.missing[need]}")
    for ev in fx["events"]:
        try:
            d.apply(ev)
        except Unsupported as e:
            pytest.skip(f"{d.name}: {e}")
    fails = _check(fx, d)
    has_reimport = any(e["op"] == "reimport" for e in fx["events"])
    if (
        fails
        and isinstance(d, IBMDriver)
        and has_reimport
        and all(k in ("current", "reimport") for k, _ in fails)
    ):
        pytest.xfail(IBM_REIMPORT)
    assert not fails, fails


def test_cn_reimport_writes_nothing(tmp_path):
    """On ctx, the old archive in the invalidation fixture changes nothing: every record is
    recognised by identity, nothing is published, the node stays rejected."""
    fx = next(f for f in FIXTURES if f["fixture"] == "invalidation")
    d = _driver("cn", tmp_path)
    for ev in fx["events"]:
        d.apply(ev)
    receipt = d.outcomes["before-invalidation"]
    assert receipt.entries and all(e.outcome == "accepted" for e in receipt.entries)
    assert all("already present" in e.reasons[0] for e in receipt.entries)
    assert [e.version for e in d.nest.history("nodes/fixture/office")] == [1]
    assert d.nest.read("nodes/fixture/office").status == "rejected"


def test_ctx_refuses_to_republish_a_rejected_node(tmp_path):
    """The backstop under the importer: even a direct write of the old revision is refused
    by ctx (CN A.1), and the live file is left as it was."""
    d = _driver("cn", tmp_path)
    fx = next(f for f in FIXTURES if f["fixture"] == "invalidation")
    for ev in fx["events"][:3]:  # assert, archive, invalidate
        d.apply(ev)
    path = d.nest.root / "nodes/fixture/office.md"
    before = path.read_bytes()
    from contextnest_adapter.ctx import CtxError

    with pytest.raises(CtxError):
        d.nest.write_revision(
            "nodes/fixture/office",
            body="The team meets in room 4B on Mondays.",
            frontmatter={"title": "office"},
            author="old-archive@example.org",
        )
    assert path.read_bytes() == before
    assert d.current("office") is None


def test_fixtures_are_engine_neutral():
    """Fixtures name objects, revisions and steps, never a node path, record id or engine."""
    for fx in FIXTURES:
        text = str(fx["events"]) + str(fx["expect"])
        assert "contextnest://" not in text and "nodes/" not in text, fx["fixture"]
        assert {"fixture", "title", "about", "drafts", "events", "expect"} <= set(fx)
        seqs = [e["seq"] for e in fx["events"]]
        assert seqs == sorted(seqs) == list(range(1, len(seqs) + 1)), fx["fixture"]
