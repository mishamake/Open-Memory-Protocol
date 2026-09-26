"""Context Nest vault  <->  Packer memory directory (Packer draft v0.2, Charles Packer / Letta).

The Packer draft fixes what enters the context window: every Markdown file at the root is
loaded, nested files are deferred and surfaced, every directory has a MEMORY.md, and a file
may carry a `description`. The Context Nest draft already calls itself a Packer-compliant
memory with mandatory front matter, so the export is mostly a question of where each node
lands:

    CN                                         Packer
    nodes the core selector serves             root-level files (always loaded)
      (default `pack:core`)
    every other published node                 deferred file at `<node id>.md`
    title / description                        `description` front matter
    tags                                       `tags: a, b` (as the IBM prototype's bridge
                                               writes them, without '#', since '#' starts
                                               a YAML comment)
    uri, version, status, checksum             `metadata: {"contextnest": {...}}` (read
                                               from ctx, not computed)
    floating `contextnest://` links            relative links to the exported file
    folder structure                           directories, each with a MEMORY.md
                                               (generated where the nest has none)

Importing a Packer directory gives each file a node, tags root files `#core`, and writes
`packs/core.yml` (`query: "#core"`), so `pack:core` in the nest is the Packer root tier. The
original path is kept in `metadata.omp.packer_path`, so a Packer -> CN -> Packer round trip
puts every file back where it was.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from open_memory_protocol import load_memory, validate_memory

from contextnest_adapter.ctx import CtxError
from mappings._nest import (
    PLAIN_TYPES,
    Node,
    NestIO,
    as_cn_tag,
    canon_body,
    slug_path,
    split_frontmatter,
)
from mappings.exchange import Receipt

UNMAPPABLE: dict[str, dict[str, str]] = {
    "cn_to_packer": {
        "version history, hashes, checkpoints": "A Packer directory is one point in time. "
        "The live published version is exported; its version and checksum travel in "
        "`metadata` so a reader can check it against the nest, but earlier versions do not.",
        "status other than published": "Packer has no approval state and loads what is on "
        "disk, so drafts, pending, approved and rejected nodes are not exported.",
        "selectors other than the core one": "Packer has two tiers, root and deferred. One "
        "selector picks the root; every other set is flattened into the deferred tier.",
        "type": "No Packer field. Kept in `metadata.contextnest.type`.",
        "derived_from": "No Packer field. Kept in `metadata.contextnest.derived_from`.",
        "pinned links (`@N`)": "Left as `contextnest://` URIs; a Packer harness has no "
        "versions to resolve them against.",
        "wikilinks (`[[Title]]`)": "Left as written.",
    },
    "packer_to_cn": {
        "load order and file names": "A node id is the slugged path. Root files become "
        "`#core` nodes; the original path is kept in `metadata.omp.packer_path`.",
        "`metadata` field": "Kept as `metadata.omp.packer_metadata`, not interpreted.",
        "who may write each file": "Out of scope in both drafts.",
    },
}

_LINK = re.compile(r"\]\(contextnest://([^)#@\s]+)(#[^)\s]*)?\)")
_REL_LINK = re.compile(r"\]\((?!\w+://)([^)#\s]+\.md)(#[^)\s]*)?\)")


def _yaml_scalar(s: str) -> str:
    """A one-line YAML value; JSON-quoted when a plain scalar would misparse."""
    if re.search(r"(^[\s#&*!|>'\"%@`\[\]{},-])|(:\s)|(\s#)|(\s$)", s) or s == "":
        return json.dumps(s, ensure_ascii=False)
    return s


def _published_ids(nest: NestIO) -> list[str]:
    return sorted(d["id"] for d in nest.ctx.run_json("list", "--status", "published", "--json"))


def _placement(nest: NestIO, core: str | None) -> tuple[dict[str, str], dict[str, Node]]:
    """node id -> path in the Packer directory, and the live nodes read to decide it."""
    try:
        core_ids = set(nest.served(core)) if core else set()
    except CtxError:
        core_ids = set()  # e.g. no such pack
    out: dict[str, str] = {}
    nodes: dict[str, Node] = {}
    taken: set[str] = set()
    for node_id in _published_ids(nest):
        node = nodes[node_id] = nest.read(node_id)
        path = node.omp.get("packer_path")
        if not path:
            if node_id in core_ids:
                path = node_id.rsplit("/", 1)[-1] + ".md"
                if path in taken or path == "MEMORY.md":
                    path = slug_path(node_id).replace("/", "--") + ".md"
            else:
                path = f"{node_id}.md"
        taken.add(path)
        out[node_id] = path
    return out, nodes


def export_packer(
    nest: NestIO, out_dir: str | Path, *, core: str | None = "pack:core"
) -> tuple[list[Path], Receipt]:
    """Write the nest's published nodes as a Packer memory directory and validate it."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    receipt = Receipt("export", counterpart="packer-v0.2")
    placement, nodes = _placement(nest, core)
    for node_id in nest.ids(include_rejected=True):
        if node_id not in placement:
            receipt.add(
                f"contextnest://{node_id}", "omitted", None,
                "not published; a Packer harness loads whatever is on disk",
            )
    written: list[Path] = []
    for node_id, rel in placement.items():
        node = nodes[node_id]
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        body = _rewrite_links_out(canon_body(node.body), rel, placement)
        cn: dict[str, Any] = {
            "uri": node.uri,
            "version": node.version,
            "status": node.status,
            "type": node.frontmatter.get("type", "document"),
        }
        if node.frontmatter.get("checksum"):
            cn["checksum"] = node.frontmatter["checksum"]
        if node.frontmatter.get("derived_from"):
            cn["derived_from"] = list(node.frontmatter["derived_from"])
        desc = str(node.frontmatter.get("description") or node.title)
        fm = [f"description: {_yaml_scalar(desc)}"]
        if node.tags:
            fm.append("tags: " + ", ".join(t.lstrip("#") for t in node.tags))
        fm.append("metadata: " + json.dumps({"contextnest": cn}, ensure_ascii=False))
        target.write_text("---\n" + "\n".join(fm) + "\n---\n" + body, encoding="utf-8")
        written.append(target)
        receipt.add(
            node.uri, "transformed", rel,
            "live published version only; version and checksum kept in metadata",
        )
    written += _write_indexes(out, nest.name, placement)
    validate_memory(out)
    return written, receipt


def _rewrite_links_out(body: str, here: str, placement: dict[str, str]) -> str:
    def sub(m: re.Match[str]) -> str:
        target = placement.get(m.group(1))
        if target is None:
            return m.group(0)
        rel = os.path.relpath(target, os.path.dirname(here) or ".")
        return f"]({Path(rel).as_posix()}{m.group(2) or ''})"

    return _LINK.sub(sub, body)


def _write_indexes(out: Path, name: str, placement: dict[str, str]) -> list[Path]:
    """A MEMORY.md for every directory that has none (Packer: every directory needs one)."""
    dirs: set[Path] = {Path(".")}
    for rel in placement.values():
        p = Path(rel).parent
        while p != Path("."):
            dirs.add(p)
            p = p.parent
    descriptions = {
        rel: _desc_of(out / rel) for rel in placement.values()
    }
    written = []
    for d in sorted(dirs, key=lambda p: len(p.parts)):
        idx = out / d / "MEMORY.md"
        if idx.exists():
            continue
        files = sorted(
            r for r in placement.values() if Path(r).parent == d and Path(r).name != "MEMORY.md"
        )
        subdirs = sorted(p.name for p in dirs if p != Path(".") and p.parent == d)
        if d == Path("."):
            title = name
            desc = f"Root index of the Context Nest '{name}', exported as a Packer memory."
        else:
            title, desc = d.name, f"Index of {d.as_posix()}/ from the Context Nest '{name}'."
        lines = [f"---\ndescription: {_yaml_scalar(desc)}\n---\n# {title}\n"]
        if files:
            lines.append("")
            lines += [f"- `{Path(f).name}`: {descriptions[f]}" for f in files]
        if subdirs:
            lines.append("")
            lines += [f"- `{s}/`: read `{s}/MEMORY.md` for what is there." for s in subdirs]
        idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(idx)
    return written


def _desc_of(path: Path) -> str:
    fm, _ = split_frontmatter(path.read_text(encoding="utf-8"))
    return str(fm.get("description") or path.stem)


# --------------------------------------------------------------------------- import


def _packer_fields(text: str) -> tuple[dict[str, Any], str]:
    try:
        fm, body = split_frontmatter(text)
    except yaml.YAMLError:
        return {}, text
    return fm, body


def import_packer(
    nest: NestIO,
    packer_dir: str | Path,
    *,
    author: str = "user",
    prefix: str = "nodes",
    core_tag: str = "#core",
) -> Receipt:
    """Load a Packer memory directory with the python-loader-validator, then write each
    file as a node through `ctx publish`."""
    root = Path(packer_dir)
    memory = load_memory(root)  # raises if the directory is not a valid Packer memory
    receipt = Receipt("import", counterpart="packer-v0.2")
    files = [(f, True) for f in memory.core_files] + [(f, False) for f in memory.external_files]
    ids: dict[str, str] = {}
    for f, _ in files:
        rel = f.relative_path.as_posix()
        stem = rel.removesuffix(".md")
        ids[rel] = stem if stem.startswith("nodes/") else f"{prefix}/{slug_path(stem)}"
    for f, is_core in files:
        rel = f.relative_path.as_posix()
        fm, body = _packer_fields(f.read())
        reasons: list[str] = []
        tags_raw = fm.get("tags") or []
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split(",")]
        else:
            tags = [str(t) for t in tags_raw]
        tags = [as_cn_tag(t) for t in tags if t]
        if is_core:
            tags.append(core_tag)
            reasons.append(f"root file: tagged {core_tag} so pack:core loads it")
        heading = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        title = heading.group(1).strip() if heading else f.relative_path.stem
        md = fm.get("metadata")
        cn_meta = md.get("contextnest") if isinstance(md, dict) else None
        ntype = (cn_meta or {}).get("type", "document")
        omp: dict[str, Any] = {"packer_path": rel}
        if fm.get("metadata") and not cn_meta:
            omp["packer_metadata"] = fm["metadata"]
            reasons.append("`metadata` kept as metadata.omp.packer_metadata")
        body = _rewrite_links_in(canon_body(body), rel, ids)
        node_id = ids[rel]
        try:
            cp = nest.write_revision(
                node_id,
                body=body,
                frontmatter={
                    "title": title,
                    "type": ntype if ntype in PLAIN_TYPES else "document",
                    "tags": sorted(set(tags)) or None,
                    "description": fm.get("description") or None,
                    "derived_from": (cn_meta or {}).get("derived_from"),
                    "metadata": {"omp": omp},
                },
                author=str(fm.get("author") or author),
                note=f"imported from Packer memory: {rel}",
                agent="packer-import" if str(fm.get("ai_generated", "")).lower() == "true"
                else None,
            )
        except CtxError as e:
            receipt.add(rel, "rejected", None, f"ctx refused: {e}")
            continue
        outcome = "transformed" if reasons else "accepted"
        receipt.add(rel, outcome, f"contextnest://{node_id}@{cp}", *reasons)
    packs = nest.root / "packs"
    packs.mkdir(exist_ok=True)
    core_pack = packs / "core.yml"
    if not core_pack.exists():
        core_pack.write_text(
            f'id: core\nlabel: Packer root tier\nquery: "{core_tag}"\n', encoding="utf-8"
        )
    nest.ctx.run("index")
    return receipt


def _rewrite_links_in(body: str, here: str, ids: dict[str, str]) -> str:
    base = os.path.dirname(here)

    def sub(m: re.Match[str]) -> str:
        target = os.path.normpath(os.path.join(base, m.group(1))).replace(os.sep, "/")
        node_id = ids.get(target)
        if node_id is None:
            return m.group(0)
        return f"](contextnest://{node_id}{m.group(2) or ''})"

    return _REL_LINK.sub(sub, body)
