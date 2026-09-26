"""Two independent engines driven by the same engine-neutral fixtures (../fixtures/*.json).

- IBMDriver runs them on the IBM prototype's MemoryStore (prototypes/ibm-draft-memory-records).
- CNDriver runs them on a real nest through `ctx`, using the mappings for archives.

The engines share no code: IBMDriver never touches ctx, and CNDriver's archive is an IBM
bundle produced by mappings.ibm, so each archive crosses from one data model to the other.
A driver answers four questions a fixture can ask: which revision of an object is current,
the object's revision history, which revision was current after step N, and which input
revisions a derived revision names.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load_fixtures() -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(FIXTURES.glob("*.json"))]


class Unsupported(Exception):
    """The engine has no counterpart for this operation; the reason says why."""


# --------------------------------------------------------------------------- IBM


class IBMDriver:
    name = "ibm-prototype"
    # capability -> None if supported, else the reason it is not
    missing = {
        "forget": "the IBM draft v0.1 defines Delete but no tombstone, so there is nothing to "
        "stop an archive from bringing a deleted record back; out of scope for that prototype",
    }

    def __init__(self, tmp: Path) -> None:
        from ibm_memory import MemoryStore, Provenance

        self.Provenance = Provenance
        self.store = MemoryStore("ibm-fixture")
        self.rev: dict[str, str] = {}  # revision label -> record id
        self.label: dict[str, str] = {}  # record id -> revision label
        self.head: dict[str, str] = {}  # object -> latest record id
        self.archives: dict[str, Any] = {}
        self.outcomes: dict[str, Any] = {}

    @staticmethod
    def t(seq: int) -> str:
        """A fixture clock: step N happens at second N, so as-of reads need no sleeping."""
        return f"2026-10-01T00:00:{seq:02d}+00:00"

    def apply(self, ev: dict[str, Any]) -> None:
        op, seq = ev["op"], ev["seq"]
        if op in ("assert", "supersede", "consolidate"):
            prev = self.head.get(ev["object"]) if op == "supersede" else None
            old = self.store.get(prev) if prev else None
            source = list(ev.get("evidence", []))
            if op == "consolidate":
                source += [self.rev[i] for i in ev["inputs"]]
            rec = self.store.write(
                ev["body"],
                author=ev["actor"],
                provenance=self.Provenance(
                    ai_used=bool(ev.get("agent")), agent=ev.get("agent"), model=ev.get("model")
                ),
                semantic_tags=[ev.get("role", "human_assertion")],
                scope_tags=[f"object:{ev['object']}"],
                source_material=source,
                supersedes=prev,
                version=(old.lifecycle.version + 1) if old else 1,
                created_at=self.t(seq),
            )
            if prev:  # the store's override(), on the fixture clock
                self.store.invalidate(prev, at=self.t(seq))
            self.rev[ev["revision"]] = rec.id
            self.label[rec.id] = ev["revision"]
            self.head[ev["object"]] = rec.id
        elif op == "invalidate":
            self.store.invalidate(self.head[ev["object"]], at=self.t(seq))
        elif op == "archive":
            self.archives[ev["label"]] = self.store.export()
        elif op == "reimport":
            imported = self.store.import_bundle(self.archives[ev["label"]])
            for r in imported:
                oid = r.origin.split(":", 1)[1]
                if oid in self.label:
                    self.label[r.id] = self.label[oid]
            self.outcomes[ev["label"]] = [r.id for r in imported]
        elif op == "forget":
            raise Unsupported(self.missing["forget"])
        else:
            raise ValueError(op)

    def _records(self, obj: str):
        return [r for r in self.store.all() if f"object:{obj}" in r.scope_tags]

    def current(self, obj: str) -> str | None:
        valid = [r for r in self._records(obj) if r.is_valid]
        if not valid:
            return None
        return self.label.get(max(valid, key=lambda r: r.lifecycle.created_at).id)

    def current_labels(self, obj: str) -> list[str]:
        return sorted({self.label.get(r.id, r.id) for r in self._records(obj) if r.is_valid})

    def history(self, obj: str) -> list[str]:
        recs = sorted(
            (r for r in self._records(obj) if r.origin is None),
            key=lambda r: r.lifecycle.version,
        )
        return [self.label[r.id] for r in recs]

    def as_of(self, seq: int, obj: str) -> str | None:
        valid = [r for r in self.store.as_of(self.t(seq)) if f"object:{obj}" in r.scope_tags]
        valid = [r for r in valid if r.origin is None]
        return self.label[valid[-1].id] if valid else None

    def lineage(self, rev: str) -> list[str]:
        rec = self.store.get(self.rev[rev])
        return sorted(self.label[s] for s in rec.lifecycle.source_material if s in self.label)


# --------------------------------------------------------------------------- Context Nest


class CNDriver:
    name = "contextnest-ctx"

    def __init__(self, tmp: Path) -> None:
        from mappings._nest import NestIO

        self.nest = NestIO.init(tmp / "nest", "fixture nest")
        self.rev: dict[str, tuple[str, int, int]] = {}  # label -> (node id, version, checkpoint)
        self.seq_cp: dict[int, int | None] = {}
        self.archives: dict[str, Any] = {}
        self.outcomes: dict[str, Any] = {}
        self.missing: dict[str, str] = {}
        if not self.nest.has_command("forget"):
            self.missing["forget"] = (
                "ctx forget is not released yet (Context Nest draft §6.3 is proposed and being "
                "built); this fixture states the expected behaviour and runs once ctx has it"
            )

    @staticmethod
    def node(obj: str) -> str:
        return f"nodes/fixture/{obj}"

    def apply(self, ev: dict[str, Any]) -> None:
        from mappings import ibm

        op, seq = ev["op"], ev["seq"]
        if op in ("assert", "supersede", "consolidate"):
            node_id = self.node(ev["object"])
            derived = None
            if op == "consolidate":
                derived = [
                    f"contextnest://{self.rev[i][0]}@{self.rev[i][2]}" for i in ev["inputs"]
                ]
            client = {"model": ev["model"]} if ev.get("model") else None
            cp = self.nest.write_revision(
                node_id,
                body=ev["body"],
                frontmatter={
                    "title": ev["object"],
                    "type": "document",
                    "tags": [f"#{ev.get('role', 'human_assertion')}"],
                    "derived_from": derived,
                    "metadata": {"omp": {"evidence": ev.get("evidence", [])}},
                },
                author=ev["actor"],
                note=f"fixture {ev['revision']}",
                agent=ev.get("agent"),
                client=client,
            )
            version = self.nest.history(node_id)[-1].version
            self.rev[ev["revision"]] = (node_id, version, cp)
        elif op == "invalidate":
            self.nest.set_status(self.node(ev["object"]), "rejected")
        elif op == "archive":
            bundle, _manifest, _receipt = ibm.export_bundle(self.nest)
            self.archives[ev["label"]] = bundle
        elif op == "reimport":
            self.outcomes[ev["label"]] = ibm.import_bundle(self.nest, self.archives[ev["label"]])
        elif op == "forget":
            if "forget" in self.missing:
                raise Unsupported(self.missing["forget"])
            # Expected invocation once released (CN §6.3.1: node plus a closed reason code).
            self.nest.ctx.run(
                "forget", self.node(ev["object"]), "--reason", ev["reason_code"], "--yes"
            )
        else:
            raise ValueError(op)
        self.seq_cp[seq] = self.nest.latest_checkpoint()

    def _label(self, node_id: str, version: int) -> str | None:
        return next((k for k, v in self.rev.items() if v[0] == node_id and v[1] == version), None)

    def current(self, obj: str) -> str | None:
        node_id = self.node(obj)
        if not (self.nest.root / f"{node_id}.md").exists():
            return None
        live = self.nest.read(node_id)
        if live.status != "published":  # the resolver serves published only (CN A.1)
            return None
        return self._label(node_id, live.version)

    def current_labels(self, obj: str) -> list[str]:
        cur = self.current(obj)
        return [cur] if cur else []

    def history(self, obj: str) -> list[str]:
        node_id = self.node(obj)
        return [
            self._label(node_id, e.version) or f"v{e.version}"
            for e in self.nest.history(node_id)
            if e.published_at
        ]

    def as_of(self, seq: int, obj: str) -> str | None:
        cp = self.seq_cp.get(seq)
        if cp is None:
            return None
        node = self.nest.pinned(self.node(obj), cp)
        return None if node is None else self._label(node.id, node.version)

    def lineage(self, rev: str) -> list[str]:
        node_id, version, _ = self.rev[rev]
        node = self.nest.reconstruct(node_id, version)
        out = []
        for uri in node.frontmatter.get("derived_from") or []:
            path, _, cp = str(uri).removeprefix("contextnest://").partition("@")
            out.append(next(k for k, v in self.rev.items() if v[0] == path and str(v[2]) == cp))
        return sorted(out)

    # CN-only checks the resurrection fixture asks for, once forget exists
    def is_forgotten(self, obj: str) -> bool:
        return self.nest.read(self.node(obj)).status == "forgotten"

    def review_required(self, obj: str) -> bool:
        return bool(self.nest.read(self.node(obj)).frontmatter.get("review_required"))

    def verify_passes(self) -> bool:
        return bool(self.nest.ctx.run_json("verify", "--json").get("valid"))
