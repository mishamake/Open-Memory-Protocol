"""Live-model run of the Context Nest adapter, in the shape of PR #7's live runs.

Seeds a fresh nest per scenario, runs each scenario on each model, and writes every
tool call, tool result, final answer and read trace to live/results/<model>/<scenario>.json.
The key comes from the environment (OPENROUTER_API_KEY); nothing is written back to it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from langchain.agents import create_agent
from langchain.messages import AIMessage, HumanMessage, ToolMessage

from contextnest_adapter.ctx import CtxClient
from contextnest_adapter.middleware import ContextNestMiddleware
from contextnest_adapter.models import resolve_model

HERE = Path(__file__).resolve().parent
SEED = HERE.parent / "examples" / "seed-nest.sh"
OUT = HERE / "results"
MODELS = sys.argv[1:] or [
    "openrouter:nvidia/nemotron-3-nano-30b-a3b",
    "openrouter:moonshotai/kimi-k3",
]


def ctx(nest: Path, *args: str) -> str:
    env = {**os.environ, "CONTEXTNEST_VAULT_PATH": str(nest)}
    return subprocess.run(
        ["ctx", *args], cwd=nest, env=env, check=True, capture_output=True, text=True
    ).stdout


def fresh_nest() -> Path:
    d = Path(tempfile.mkdtemp(prefix="nest-")) / "nest"
    subprocess.run(["sh", str(SEED), str(d)], check=True, capture_output=True)
    # A document with real history: v1 said Sept 30, v2 says Oct 2 (only v2 is served).
    ctx(
        d,
        "add",
        "nodes/projects/omp-schedule",
        "--title",
        "OMP schedule",
        "--tags",
        "#project-omp",
        "--body",
        "First drafts are due Tuesday 2026-09-30.",
    )
    ctx(
        d,
        "update",
        "nodes/projects/omp-schedule",
        "--body",
        "First drafts are due Friday 2026-10-02 (moved from 2026-09-30).",
    )
    # An unreviewed, agent-written claim that must never be served.
    ctx(
        d,
        "add",
        "nodes/memory/deadline-rumor",
        "--title",
        "Deadline rumor",
        "--tags",
        "#project-omp",
        "--body",
        "Someone said drafts are now due 2026-10-20.",
    )
    ctx(d, "update", "nodes/memory/deadline-rumor", "--status", "pending_review")
    ctx(d, "index")
    return d


def messages_to_trace(msgs) -> list[dict]:
    out = []
    for m in msgs:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls or []:
                out.append({"tool_call": tc["name"], "args": tc["args"]})
            if m.text.strip():
                out.append({"assistant": m.text.strip()})
        elif isinstance(m, ToolMessage):
            out.append({"tool_result": m.name, "content": str(m.content)[:1500]})
        elif isinstance(m, HumanMessage):
            out.append({"user": m.text})
    return out


def run_agent(
    model, nest: Path, turns: list[str], *, load=None, writable=False, between=None
) -> dict:
    mw = ContextNestMiddleware(CtxClient(nest), load=load, writable=writable)
    agent = create_agent(model=model, tools=[], middleware=[mw])
    msgs: list = []
    for i, t in enumerate(turns):
        if between and i in between:
            between[i](nest)
        msgs.append(HumanMessage(content=t))
        msgs[:] = agent.invoke({"messages": msgs})["messages"]
    return {"trace": messages_to_trace(msgs), "reads": mw.reads, "proposed": mw.proposed}


def publish_proposals(nest: Path) -> None:
    data = json.loads(ctx(nest, "list", "--json"))
    docs = data if isinstance(data, list) else data.get("documents", [])
    for d in docs:
        p = d.get("path") or d.get("id")
        if p and p.startswith("nodes/memory/") and "deadline-rumor" not in p:
            ctx(nest, "update", p, "--status", "published")


SCENARIOS = {
    # Sruly's finding 1: do models treat a fully loaded set as an index and re-fetch?
    "loaded-in-full": {
        "load": "pack:core",
        "turns": ["Who is Sruly and what does he prefer? Answer from memory."],
    },
    # Stale version vs current, plus an unreviewed rumor in the same tag space.
    "stale-vs-current": {
        "turns": ["When are OMP first drafts due? Check your memory and cite the source URI."],
    },
    # Sruly's finding 3b: do models hand back short ids / prefixes?
    "id-handling": {
        "turns": ["Load the note about the OMP areas of concern and list the areas."],
    },
    # Propose, then (a) not served before review, (b) served after a person publishes.
    "propose-gate": {
        "writable": True,
        "turns": [
            "Remember that I prefer email over Slack.",
            "Using only your memory, which channel do I prefer? If it isn't in memory, say so.",
            "Using only your memory, which channel do I prefer? If it isn't in memory, say so.",
        ],
        "between": {2: publish_proposals},
    },
}


def resolve_stability(nest: Path) -> dict:
    """Not a model test: same selector, 5 runs x 2 copies, full and graph mode (2.7.0)."""
    copy = nest.parent / "copy"
    subprocess.run(["cp", "-r", str(nest), str(copy)], check=True)
    rows = {}
    for hops in (0, 1, 2):
        sets = set()
        for n in (nest, copy):
            c = CtxClient(n)
            for _ in range(5):
                sets.add(tuple(c.query("(#core | #project-omp) -#archive", hops=hops).ids))
        rows[f"hops={hops}"] = {"distinct_sets": len(sets), "ids": list(next(iter(sets)))}
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "resolve-stability.json").write_text(
        json.dumps(resolve_stability(fresh_nest()), indent=2)
    )
    for spec in MODELS:
        model = resolve_model(spec, temperature=0, max_tokens=2000)
        mdir = OUT / spec.split("/")[-1]
        mdir.mkdir(exist_ok=True)
        for name, sc in SCENARIOS.items():
            try:
                res = run_agent(model, fresh_nest(), **sc)
            except Exception as e:  # noqa: BLE001 - keep going; record the failure
                res = {"error": f"{type(e).__name__}: {e}"}
            (mdir / f"{name}.json").write_text(json.dumps(res, indent=2))
            print(f"{spec} {name}: {'ERROR' if 'error' in res else 'ok'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
