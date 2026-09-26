"""Reading and writing nest nodes for the mappings, through `ctx`.

What this module does itself: parse and write the YAML front matter of a Markdown file, and
put a file in a nest directory. That is field-shape work, the same thing a text editor does.

What it leaves to `ctx`: every version number, checksum, content hash, chain hash,
checkpoint, reconstruction and status transition. A new revision is written as a file and
then sealed with `ctx publish`; an old revision is read back with `ctx reconstruct`; a point
in time is a checkpoint number that `ctx checkpoint list` reports. Nothing here computes a
hash or edits `.versions/`.

Writes need a local nest directory (the file has to be put somewhere). Reads work against a
local nest; hosted nests are reachable through the same `ctx` commands only where `ctx`
supports them remotely.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from contextnest_adapter.ctx import CtxClient, CtxError

_FM = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)

# Node types a mapping may assign without the typed block ctx requires for
# `source`, `skill` and `pdf` (CN §1.6, §13).
PLAIN_TYPES = (
    "document", "snippet", "glossary", "persona", "prompt", "tool", "reference",
    "agent", "artifact", "table",
)

# CN tag grammar (CN §1.5 rule 6, as enforced by ctx): optional '#', a letter, then
# letters, digits, '_', ':' or '-'.
TAG_RE = re.compile(r"^#?[A-Za-z][A-Za-z0-9_:-]*$")

STATUSES = ("draft", "pending_review", "approved", "published", "rejected")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def iso(ts: str | None) -> str | None:
    """A ctx timestamp ('...Z') in the IBM prototype's form ('...+00:00'), so the IBM
    store's string comparisons order them correctly."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FM.match(text)
    if not m:
        return {}, text
    data = yaml.safe_load(m.group(1)) or {}
    return (_plain(data) if isinstance(data, dict) else {}), text[m.end() :]


def _plain(v: Any) -> Any:
    """YAML timestamps back to ISO strings, so values compare as ctx wrote them."""
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    if isinstance(v, datetime):
        return v.isoformat().replace("+00:00", "Z")
    return v


def canon_body(body: str) -> str:
    """The body with surrounding blank lines removed and one trailing newline. Bodies are
    compared and exchanged in this form; the blank line ctx keeps after the front matter
    is layout, not content."""
    return body.strip("\n") + "\n"


def join_frontmatter(fm: dict[str, Any], body: str) -> str:
    block = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=10_000).strip()
    return f"---\n{block}\n---\n\n{canon_body(body)}"


def slug_path(text: str) -> str:
    """A string made safe as a node id path: lowercase, [a-z0-9-] per segment."""
    segs = []
    for seg in text.replace("\\", "/").split("/"):
        s = re.sub(r"[^a-z0-9]+", "-", seg.lower()).strip("-")
        if s:
            segs.append(s)
    return "/".join(segs) or "node"


def is_cn_tag(tag: str) -> bool:
    return bool(TAG_RE.match(tag))


def as_cn_tag(tag: str) -> str:
    return tag if tag.startswith("#") else f"#{tag}"


@dataclass
class Node:
    """One revision of a node: front matter and body, as `ctx` stored them."""

    id: str
    frontmatter: dict[str, Any]
    body: str

    @property
    def uri(self) -> str:
        return f"contextnest://{self.id}"

    @property
    def status(self) -> str:
        return str(self.frontmatter.get("status", "draft"))

    @property
    def version(self) -> int:
        return int(self.frontmatter.get("version") or 0)

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title") or self.id.rsplit("/", 1)[-1])

    @property
    def tags(self) -> list[str]:
        return [str(t) for t in self.frontmatter.get("tags") or []]

    @property
    def metadata(self) -> dict[str, Any]:
        md = self.frontmatter.get("metadata") or {}
        return md if isinstance(md, dict) else {}

    @property
    def omp(self) -> dict[str, Any]:
        """Cross-draft fields these mappings keep under `metadata.omp` (CN §14 extension)."""
        v = self.metadata.get("omp") or {}
        return v if isinstance(v, dict) else {}


@dataclass
class VersionEntry:
    """A row of `ctx history --json`. Fields are what ctx reports; nothing is recomputed."""

    version: int
    edited_by: str
    edited_at: str
    published_at: str | None = None
    note: str | None = None
    content_hash: str | None = None
    chain_hash: str | None = None
    client: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> VersionEntry:
        return cls(
            version=int(d["version"]),
            edited_by=d.get("edited_by", ""),
            edited_at=d.get("edited_at", ""),
            published_at=d.get("published_at"),
            note=d.get("note"),
            content_hash=d.get("content_hash"),
            chain_hash=d.get("chain_hash"),
            client=dict(d.get("client") or {}),
        )


class NestIO:
    """The `ctx` calls the mappings need, on top of the adapter's `CtxClient`."""

    def __init__(self, ctx: CtxClient | str | Path) -> None:
        self.ctx = ctx if isinstance(ctx, CtxClient) else CtxClient(ctx)
        self._checkpoints: list[dict[str, Any]] | None = None

    # ---------------------------------------------------------------- setup
    @classmethod
    def init(cls, path: str | Path, name: str) -> NestIO:
        """A new, empty nest made by `ctx init`."""
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        io = cls(CtxClient(p))
        io.ctx.run("init", "-n", name)
        return io

    @property
    def root(self) -> Path:
        if self.ctx.cwd is None:
            raise CtxError("this operation needs a local nest directory, not a vault alias")
        return self.ctx.cwd

    @property
    def name(self) -> str:
        try:
            info = self.ctx.run_json("info", "--json")
            return (info.get("config") or {}).get("name") or self.root.name
        except CtxError:
            return self.root.name

    # ---------------------------------------------------------------- reads
    def ids(self, *, include_rejected: bool = True) -> list[str]:
        """Every node id, drafts included. `ctx list` hides rejected nodes unless asked."""
        seen = [d["id"] for d in self.ctx.run_json("list", "--json")]
        if include_rejected:
            seen += [d["id"] for d in self.ctx.run_json("list", "--status", "rejected", "--json")]
        return sorted(set(seen))

    def read(self, node_id: str) -> Node:
        """The live file (any status, rejected included)."""
        raw = self.ctx.run("read", node_id, "--raw")
        raw = raw[:-1] if raw.endswith("\n") else raw  # console.log's newline
        fm, body = split_frontmatter(raw)
        return Node(node_id, fm, body)

    def history(self, node_id: str) -> list[VersionEntry]:
        out = self.ctx.run("history", node_id, "--json").strip()
        if not out.startswith("{"):
            return []  # "No version history for ..." (never published)
        return [VersionEntry.from_json(v) for v in json.loads(out).get("versions", [])]

    def reconstruct(self, node_id: str, version: int) -> Node:
        """Revision `version` of a node, rebuilt by `ctx reconstruct` (CN §6.1)."""
        raw = self.ctx.run("reconstruct", node_id, str(version))
        raw = raw[:-1] if raw.endswith("\n") else raw  # console.log's newline
        fm, body = split_frontmatter(raw)
        return Node(node_id, fm, body)

    def checkpoints(self) -> list[dict[str, Any]]:
        """`ctx checkpoint list`, cached until this object next writes."""
        if self._checkpoints is None:
            try:
                data = self.ctx.run_json("checkpoint", "list", "--json", "-n", "1000000")
            except CtxError:
                data = []  # "No checkpoints found." is plain text
            self._checkpoints = data if isinstance(data, list) else []
        return self._checkpoints

    def latest_checkpoint(self) -> int | None:
        cps = self.checkpoints()
        return int(cps[-1]["checkpoint"]) if cps else None

    def checkpoint_of(self, node_id: str, version: int) -> int | None:
        """The checkpoint that sealed `version` of `node_id` (its pinned URI is `id@N`)."""
        for cp in self.checkpoints():
            versions = cp["document_versions"]
            if cp.get("triggered_by") == node_id and versions.get(node_id) == version:
                return int(cp["checkpoint"])
        for cp in self.checkpoints():  # e.g. `ctx publish --all`, one checkpoint for many
            if cp["document_versions"].get(node_id) == version:
                return int(cp["checkpoint"])
        return None

    def pinned(self, node_id: str, checkpoint: int) -> Node | None:
        """`contextnest://<id>@<checkpoint>` (CN §4.1): the version checkpoint N recorded,
        or None if the node was not published at N. The map comes from `ctx checkpoint list`
        and the content from `ctx reconstruct`."""
        cp = next((c for c in self.checkpoints() if int(c["checkpoint"]) == checkpoint), None)
        if cp is None:
            return None
        v = cp["document_versions"].get(node_id)
        return None if v is None else self.reconstruct(node_id, int(v))

    def served(self, selector: str) -> list[str]:
        """Ids the resolver serves for a selector (published only, CN A.1)."""
        return self.ctx.query(selector, hops=0).ids

    # ---------------------------------------------------------------- writes
    def write_revision(
        self,
        node_id: str,
        *,
        body: str,
        frontmatter: dict[str, Any],
        author: str,
        note: str | None = None,
        agent: str | None = None,
        client: dict[str, str] | None = None,
        publish: bool = True,
    ) -> int | None:
        """Write the next revision of a node as a file, then let `ctx publish` seal it.

        `frontmatter` is merged over the live file's, so `version`, `created_at` and
        `checksum` stay what ctx last wrote; ctx bumps and recomputes them on publish.
        Returns the checkpoint the publish cut (None when `publish=False`).
        """
        path = self.root / f"{node_id}.md"
        base: dict[str, Any] = {}
        before = path.read_bytes() if path.exists() else None
        if before is not None:
            base, _ = split_frontmatter(before.decode("utf-8"))
        fm = {**base, **{k: v for k, v in frontmatter.items() if v is not None}}
        fm.setdefault("status", "draft")
        fm.setdefault("created_at", now_iso())
        for k in [k for k, v in frontmatter.items() if v is None]:
            fm.pop(k, None)
        self._checkpoints = None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(join_frontmatter(fm, body), encoding="utf-8")
        if not publish:
            self.ctx.run("index")
            return None
        args: list[str] = []
        if agent:
            args += ["--agent", agent]
        for k, v in (client or {}).items():
            args += ["--client", f"{k}={v}"]
        args += ["publish", node_id, "-a", author]
        if note:
            args += ["-m", note]
        try:
            self.ctx.run(*args)
        except CtxError:
            # ctx refused (for example a rejected node, CN A.1): put the live file back
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
            raise
        return self.latest_checkpoint()

    def set_status(self, node_id: str, status: str) -> None:
        """A metadata-only transition (CN A.1): no version is cut, no checkpoint emitted."""
        self._checkpoints = None
        self.ctx.run("update", node_id, "--status", status)

    def has_command(self, name: str) -> bool:
        """Whether this `ctx` build has a subcommand (used to gate `forget`)."""
        try:
            self.ctx.run(name, "--help")
            return True
        except CtxError:
            return False
