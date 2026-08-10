# Atrinik content

This repository owns Atrinik's authored archetypes, maps, editor material, and
the collection tools that turn those sources into server runtime input.
See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the ownership boundaries
and source-to-runtime validation flow.

This checkout's `1.x` branch is the maintained classic release line. See
[`docs/RELEASE_LINES.md`](docs/RELEASE_LINES.md) for target selection,
backport/forward-port rules, the bounded semantic-release channel, and exact
runtime compatibility metadata. `1.x` packages are explicitly not
replacement-ready.

The content has heterogeneous licensing. `arch/COPYING`, `maps/COPYING`, and
the nearest `LICENSE` file for an asset are authoritative; the repository does
not apply one blanket license to every file. Releases preserve those notices
and include a machine-readable digest manifest.

Build and validate a runtime tree without modifying authored sources:

```sh
python3 tools/build_runtime.py --output build/runtime
python3 tools/validate.py
```

The result contains collected files under `lib/`, compiled map interfaces and
authored maps under `maps/`, attribution files under `attribution/`, and
`manifest.json` with the SHA-256 of every packaged file.

The typed content catalog defines stable identities and validates authored
cross-references before collection. See
[`docs/CONTENT_IDENTITIES.md`](docs/CONTENT_IDENTITIES.md) for its commands,
source-of-truth table, and rename/removal policy.

The authoritative field schema closes and types the authored field surface and
generates loader/compiler, editor, documentation, and parser-neutral logical
metadata. See [`docs/CONTENT_SCHEMA.md`](docs/CONTENT_SCHEMA.md) for the logical
model, generated outputs, custom namespace policy, and migration rules. Validate
the checked-in projections and the entire legacy corpus with:

```sh
python3 -m tools.content_schema validate --root .
```

The canonical per-ID plural vocabulary, drift-safe one-time migration, permanent
completeness audit, and cross-line comparison are documented in
[`docs/ARCHETYPE_PLURALS.md`](docs/ARCHETYPE_PLURALS.md).

Versioned legacy ADS grammar contracts, consumer ownership, interchange schemas,
and the lossless parity corpus live under `contracts/content-v1/`. See
[`docs/CONTENT_GRAMMAR_CONTRACTS.md`](docs/CONTENT_GRAMMAR_CONTRACTS.md) for the
authoritative server sources, compatibility rules, fixture coverage, and
read-only inspection command.

`tools/content_core` is the production byte-lossless legacy ADS core. Its
versioned `tools/atrinik-content` CLI provides bounded inspection, validation,
semantic comparison, catalog search, and dry-run-first primitive transactions.
See [`docs/CONTENT_CORE.md`](docs/CONTENT_CORE.md) for the JSON contracts,
preconditions, safety boundary, exit codes, and examples.

The accepted future authored surface is a strict, bounded JSONC dialect. See
[`docs/AUTHORED_SYNTAX_DECISION.md`](docs/AUTHORED_SYNTAX_DECISION.md) for the
decision, parser limits, cross-language implementation constraints, raw
measurements, and reproduction workflow. Evaluate the locked parity corpus
without changing authored sources:

```sh
python3 -m tools.syntax_evaluation --root . --json
```

For read-only exploratory inventories of quests, regions, artifacts, maps,
named objects, and archetype locations, run:

```sh
python3 tools/world_content_audit.py all > build/world-content-audit.json
```

Pass `quests`, `regions`, `artifacts`, or `world` for a focused report. The
audit emits deterministic JSON and never modifies authored content. It is a
review aid, not a replacement for `tools/validate.py` or the typed catalog.
