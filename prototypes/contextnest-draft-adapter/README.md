# OMP: Context Nest draft (v0.1) as an agent plug

A LangChain `create_agent` middleware for
[`early-draft-specs/draft-v0.1-contextnest.md`](../../early-draft-specs/draft-v0.1-contextnest.md).

Unlike the other prototypes here, this one does **not** reimplement the draft. The memory
system is `ctx`, the draft's reference implementation, and this package is only the harness
side: it builds `ctx` calls, parses the JSON, and wires the results into the agent. That
means the same middleware plugs into a nest on disk or a hosted nest with no code change:

```bash
nest-agent --nest ./my-nest ...        # a local nest directory
nest-agent --nest team ...             # a hosted nest registered as an alias:
                                       #   ctx vault add team --url <nest MCP url> \
                                       #     --bearer-env CONTEXTNEST_API_KEY
```

| Draft section | Here |
|---|---|
| §3 eight-key Markdown, `contextnest://` URIs | every loaded document is labelled with its URI |
| §4.2 selectors and packs | `load="pack:core"` (or any selector) is loaded in full before each model call; `nest_query(selector)` lets the model load more |
| §5 / A.1 `status` | only `published` documents are served; `nest_propose` writes `pending_review`, which the resolver will not serve until a person publishes it |
| §5 checkpoints, CN §9.2 tracing | `middleware.reads` records selector, resolved ids, and checkpoint for every set the agent saw; `ctx` also logs each access itself |
| §6.3 forget | not here: it is proposed, not implemented in `ctx` yet |

## Install

Needs Node 20+ for `ctx`, and Python 3.10+.

```bash
npm install -g @promptowl/contextnest-cli
uv sync --extra dev
```

## CLI

```bash
# a small nest built with ctx
examples/seed-nest.sh /tmp/demo-nest

# what the harness injects, no model call
uv run nest-agent --nest /tmp/demo-nest context --load pack:core

# same selector, same set, same order: 5 runs, against the nest and a copy of it
cp -r /tmp/demo-nest /tmp/demo-copy
uv run nest-agent resolve "(#core | #project-omp) -#archive" --runs 5 \
  --nests /tmp/demo-nest /tmp/demo-copy

# the agent (needs OPENROUTER_API_KEY in prototypes/.env)
uv run nest-agent --nest /tmp/demo-nest ask --load pack:core --writable \
  "When are OMP drafts due? Also remember that I prefer email."
```

## Test

```bash
uv run pytest            # needs ctx on PATH; tests skip without it
# or, with nothing installed locally:
docker build -t nest-adapter . && docker run --rm nest-adapter
```

The tests seed a real nest with `ctx` and drive the middleware with a fake model:
selector and pack resolution, set and order stability across runs and across two copies
of a nest, URI reads, the propose-then-publish gate, the notice when a proposal is
published mid-conversation, the "loaded in full" labelling, and the read trace. No network or API key needed. The same middleware was also run against a
hosted nest through a `ctx vault` alias (no code change); that run is not part of the
offline suite.

## Live runs

`live/run_live.py` runs four scenarios on real models, on a fresh nest each time, and
writes every tool call, tool result, answer and read to `live/results/`:

```bash
docker run --rm --env-file ../.env -v "$PWD/live:/app/live" nest-adapter \
  python live/run_live.py            # Nemotron 3 Nano and Kimi K3 via OpenRouter
```

Run on Nemotron 3 Nano and Kimi K3 (the models used for the other prototypes), at
temperature 0 with `ctx` 2.7.0:

| Scenario | Nemotron 3 Nano | Kimi K3 |
|---|---|---|
| A pack is preloaded; ask about it | answered from it, no tool calls | same |
| One note edited from 09-30 to 10-02, an archived old note, and a `pending_review` note saying 10-20 | 10-02, cites the edited note; the 10-20 note never appears | same |
| Ask for a note by description | search, then query by the full id from the result | same |
| Propose a memory, ask before and after a person publishes it | held back before; after, answered from the published memory | same |

The last row needed a harness change; see below. With the default `max_tokens`, Kimi K3
on OpenRouter asks for 131,072 output tokens, so the script caps it at 2,000.

## What we found

- **A selector returns a set, not scores.** Two stores holding the same nest return the
  same ids in the same order, so combining results from several nests is set union, not
  merging scores that aren't comparable. This is the case the FMP prototype hit with BM25.
- **Order was not stable at first.** In graph mode, `ctx` returned the same set in a
  different order from run to run (5 orderings in 10 runs on 2.6.0), and a hub document
  pulled in everything linking to it even at `--hops 0`. Both are fixed in the reference
  implementation ([PromptOwl/ContextNest#119](https://github.com/PromptOwl/ContextNest/pull/119),
  released in `ctx` 2.7.0): 1 ordering in 10 runs at hops 0, 1 and 2. `hops=0` still maps
  to `ctx query --full`, since it means exactly the selector's matches.
- **Full ids in, full ids out.** Neither model shortened ids. Every tool result carries
  the full `contextnest://` URI, and the models copied it back.
- **A memory published mid-conversation went unseen.** Without a notice, Nemotron
  answered from its own earlier turn ("still pending") instead of asking the nest again;
  Kimi asked again. The harness now tells the model, on the next call, which of its
  proposals have been published, loaded in full, once each. The trace records these as
  `via: "published-notice"`.
- **Agents propose; people publish.** Writing a memory as `pending_review` means a
  model-written memory cannot reach a later context window until someone approves it. The
  other drafts leave that step to the implementation.

## Where the draft was silent

- **What "load" means.** The draft names a set; it does not say whether the harness loads
  it every turn or once. Here it is resolved and injected on every model call, so a
  memory published mid-conversation is visible on the next turn.
- **Truncation.** A loaded document over 6,000 characters is cut, with a marker. The draft
  says nothing about budgets.
- **Where proposals go.** `nest_propose` writes to `nodes/memory/<slug-of-title>`. The draft
  does not reserve a folder for agent-written memory.
- **Changes during a session.** The draft says what is served, not how a harness learns
  that the served set changed mid-conversation. Here only the agent's own proposals are
  announced; changes made by others show up in the preload or the next query.
- **Hosted checkpoints.** `ctx` reports the checkpoint for local nests only, so
  `reads[].checkpoint` is `None` against a hosted nest.

## License

Apache 2.0 (see [LICENSE](../../LICENSE)) for this adapter. `ctx` is a separate program
under its own license, installed from npm and invoked as a subprocess.
