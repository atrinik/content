# Authored syntax decision

Status: accepted for the schema and lossless-core work that follows content
issue #16. Decision date: 2026-08-07.

## Decision

Atrinik's future typed authored-content schemas will use a strict JSON with
comments (JSONC) surface. The accepted dialect is UTF-8 JSON plus JavaScript-
style line and block comments. It deliberately rejects trailing commas,
duplicate keys, non-JSON numeric constants, byte-order marks, invalid Unicode,
and every extension not listed here.

This decision selects an authored surface. It does not add a production parser,
change a current file suffix, convert an archetype or map, or authorize removal
of any classic loader. Those changes belong to the schema, lossless-core, and
migration issues that depend on this decision.

The alternative prototype was a small YAML 1.2 profile with two-space block
indentation and JSON-only scalars. Both prototypes pass the fixed parity corpus.
JSONC is selected because its smaller grammar and explicit scalar rules make
the same fail-closed contract easier to implement consistently in Atrinik's C,
Python, TypeScript, and prospective Rust tooling.

## Contract selected by this decision

The machine-readable limits are
[`prototypes/authored-syntax-v1/limits.json`](../prototypes/authored-syntax-v1/limits.json).
They are part of the decision, not illustrative defaults.

| Property | Limit or policy |
| --- | ---: |
| Encoded input | 64 MiB |
| Nesting depth | 64 |
| Decoded nodes | 1,000,000 |
| Sequence items | 250,000 per sequence |
| Mapping keys | 256 per mapping |
| String or mapping key | 1 MiB UTF-8 |
| Numeric lexeme | 128 bytes |
| Integer magnitude | at most 9,007,199,254,740,991 |
| Comments | 100,000 and 4 MiB total |
| Physical lines | 250,000 |
| Physical line | 1 MiB UTF-8 |

Integers use the interoperable ±(2^53−1) range identified by
[RFC 8259 section 6](https://www.rfc-editor.org/rfc/rfc8259#section-6).
Individual schema fields will normally have much tighter semantic bounds.
Floating-point values must be finite. Mapping keys and decoded strings may not
contain NUL. Parsers must enforce limits before or while allocating, not only
after an unbounded DOM has been built.

The production dialect must preserve these rules:

- comments are `//` line comments or `/* ... */` block comments;
- strings, numbers, Boolean values, null, arrays, and objects otherwise follow
  JSON syntax;
- trailing commas, single-quoted strings, unquoted keys, hexadecimal numbers,
  unary-plus numbers, `NaN`, and infinity are errors;
- duplicate object keys are errors even when a selected library retains or
  resolves them;
- schemas are closed: unknown standard fields are errors;
- intentional extension data is allowed only below an explicit `custom`
  mapping whose children use reviewed domain-qualified namespaces; and
- parser-library nodes never escape the shared content API.

The JSON standard intentionally defines a small structured-data syntax rather
than an application schema; Atrinik's closed schemas and bounds supply the
application semantics that JSON itself does not define. See
[ECMA-404](https://ecma-international.org/publications-and-standards/standards/ecma-404/)
and [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259).

## Logical identities and physical files

Every authored document will carry an explicit stable logical `id`. A map ID
is a canonical absolute logical path such as
`/shattered_islands/world_5_65_2`. References serialize that ID, never an
absolute collected path, display name, runtime table position, or directory
iteration index.

The logical ID is independent of the source filename and suffix. Adding,
changing, or removing a suffix such as `.jsonc` must not change references.
Issue #15 will define the exact versioned root schema and field metadata; issue
#19 remains authoritative for domain ownership, rename/removal, migration, and
tombstone policy.

Unknown legacy keys cannot remain an implicit extension mechanism. Issue #15
must classify every #17 field as standard or intentionally custom. Standard
typos fail validation; plugin/script data survives only in its explicit custom
namespace.

## Comments, ordering, and source spans

Comments that are part of existing authored content are persistent nodes in
the lossless model. They are not discarded DOM trivia. The prototype proves
that comment records, blank lines, authored order, LF/CRLF state, terminal-
newline state, and exact byte spans can reconstruct every fixture byte.

The physical-record model in `tools/syntax_evaluation/model.py` is only a
surface-comparison and migration oracle. It is intentionally not the final
typed schema. Its large encoded size must not become the layout implemented by
issue #15.

Production authoring tools will need a token or concrete-syntax view in
addition to typed semantic values. JavaScript's
[node-jsonc-parser](https://github.com/microsoft/node-jsonc-parser) exposes
token offsets, comment callbacks, DOM offsets, locations, formatting edits, and
targeted modifications. Rust's
[jsonc-parser](https://docs.rs/jsonc-parser/latest/jsonc_parser/) can collect
comments and tokens and offers a manipulation-oriented CST. These APIs show
that retaining JSONC presentation data is practical, but Atrinik's public model
must define its own stable span/comment contract instead of leaking either
library's node types.

Spans in the prototype are UTF-8 byte offsets into reconstructed legacy input.
The future core must define spans against the current authored source and keep
byte offsets distinct from Unicode scalar or display-column positions.

## Why JSONC was selected

| Criterion | Strict JSONC | Constrained YAML 1.2 |
| --- | --- | --- |
| Scalar meaning | Explicit JSON spellings | Explicit only because Atrinik rejects most ordinary YAML scalars |
| Grammar surface | JSON plus two comment forms | A custom subset of block YAML, indentation, comments, and JSON scalars |
| Dangerous features | Small opt-in extension set | Standard YAML includes tags, anchors, aliases, streams, flow styles, and multiple scalar styles that Atrinik must reject |
| Duplicate-key policy | Must wrap parser and reject | Must wrap parser and compare canonical YAML keys |
| Comment/span tooling | Mature token/AST/CST options in relevant ecosystems | Ordinary representation APIs may discard presentation details; CST behavior is parser-specific |
| Deterministic formatting | Straightforward fixed JSON indentation/order | Requires a canonical subset despite YAML's intentionally flexible presentation |
| Review density in this neutral scaffold | More punctuation and bytes | Smaller and visually lighter |
| Cross-language implementation risk | Lower | Higher because every implementation must recognize the same nonstandard subset of a larger language |

The [YAML 1.2.2 specification](https://yaml.org/spec/1.2.2/) defines tags,
anchors, aliases, block/flow styles, directives, document streams, and schema-
dependent scalar resolution. It also states that parsing discards presentation
details and that construction does not use comments, key order, style, or
indentation. That flexibility is valuable for general YAML, but it creates a
larger compatibility and security contract than Atrinik needs.

JSONC is not treated as one universal standardized dialect. Each production
parser must be configured and wrapped to match Atrinik's strict policy. For
example, the ANSI C [yyjson](https://github.com/ibireme/yyjson) library has an
explicit comment-reading flag and good portability, but permits duplicate
object keys; an Atrinik adapter would still need duplicate rejection, limits,
closed-schema checks, and a separate token/comment strategy. No dependency is
selected or added by issue #16.

## Fixed parity results

The content-v1 input lock is
`126102873f5356eae0114d6876df25b54cb616719387f0bb466279bb6ecd460d`.
It covers the #17 grammar and consumer inventories, corpus manifest, and every
path-backed fixture. The corpus has 14 fixtures, including four deliberately
malformed legacy documents.

Both prototypes produced:

- 28 byte-exact round trips;
- 28 unchanged semantic inspection results;
- deterministic repeated formatting; and
- rejection of ambiguity, unsupported dialect features, and configured bound
  violations.

Tests run on Ubuntu and Windows with Python 3.13. The committed measurement was
captured on Linux with Python 3.14.4; parser correctness is not inferred from
the Linux timing run.

## Representative-map surface measurements

Maps are regular, non-symlink authored files with the exact classic map header,
sorted by `(byte size, relative path)`. The runner selects nearest-rank p10,
p50, p90, and maximum entries from 3,651 candidates, rejects maps outside the
#17 grammar, and excludes `no_save` maps that cannot exercise swap behavior.

The following values are medians of 20 observations. Time is milliseconds.

| Class | Legacy bytes / objects | JSONC bytes / ratio | JSONC encode / decode | YAML bytes / ratio | YAML encode / decode |
| --- | ---: | ---: | ---: | ---: | ---: |
| p10 | 8,400 / 259 | 196,873 / 23.44× | 8.22 / 36.80 | 140,524 / 16.73× | 32.01 / 67.57 |
| p50 | 16,002 / 576 | 413,172 / 25.82× | 15.24 / 70.90 | 295,307 / 18.45× | 62.88 / 135.49 |
| p90 | 23,908 / 848 | 611,111 / 25.56× | 28.53 / 119.94 | 437,450 / 18.30× | 90.19 / 185.19 |
| maximum | 95,618 / 2,778 | 2,199,259 / 23.00× | 83.88 / 366.86 | 1,580,686 / 16.53× | 298.04 / 613.05 |

The table preserves the captured candle timing run. The current maximum
representative map is 95,641 bytes and 2,777 objects after its portal-light
fields were authored and its same-tile fireplace and candle helpers were
transferred to the visible fixtures; its exact digest is recorded in the raw
report's `representative_maps` selection. A new complete measurement run is
required before replacing the captured expansion and timing observations.

These expansion ratios measure the same deliberately verbose physical-record
scaffold, not the future typed schema or runtime representation. YAML's lighter
punctuation makes that scaffold 28-29% smaller. The dependency-free prototype
JSONC implementation is substantially faster here, but neither Python
prototype predicts a native production parser. Grammar complexity and review
risk, not these microbenchmarks alone, determine the choice.

## Current pipeline baseline

The complete raw report is
[`prototypes/authored-syntax-v1/measurement-baseline.json`](../prototypes/authored-syntax-v1/measurement-baseline.json).
It records raw observations, min/median/p95/max summaries, map digests, tool and
component commits, clean topology state, the syntax implementation digest, and
the wrapper-runner digest.

Collection used a fresh output directory for each of three observations. It
did not flush the operating-system page cache. Median collection time was
13.635 seconds and p95 was 14.230 seconds.

The classic standalone checker was measured in a fresh collected runtime with
five processes per map. Its median wall times were 163 ms (p10), 173 ms (p50),
153 ms (p90), and 196 ms (maximum). Python 3.14 required recorded compatibility
aliases for `ConfigParser.readfp` and `xrange`; the checker source was not
modified.

The merged server's warning-as-error Debug build ran its real loaders in the
offline benchmark mode added by server PR #52. Across five processes and nine
samples per map per process:

| Class | Cold authored load | Warm lookup | Swap | Temporary reload |
| --- | ---: | ---: | ---: | ---: |
| p10 | 620 µs | 1 µs | 627 µs | 800 µs |
| p50 | 1,025 µs | 0 µs | 994 µs | 1,117 µs |
| p90 | 1,626 µs | 1 µs | 1,496 µs | 1,730 µs |
| maximum | 8,163 µs | 3 µs | 6,932 µs | 8,975 µs |

Median server initialization was 127.343 ms, median archetype initialization was
44.267 ms, and median Linux peak startup RSS was 44,204 KiB. The harness asserts
every cold/warm/swap/reload state transition; it does not accept timing-shaped
output when a map stayed resident or failed to swap.

Absolute timings are environment-specific. The value of the baseline is the
reproducible method, raw distributions, scale relationship, and exact source
provenance. It is not a release performance budget.

## Reproduction

First create or select clean worktrees for the recorded dependency commits in
the `syntax-decision` profile. Then run:

```sh
cd /workspaces/atrinik/workspace/worktrees/content/syntax-decision
python3 -m tools.syntax_evaluation --root . --json
python3 -m tools.syntax_evaluation.benchmark \
  --root . \
  --workspace-root /workspaces/atrinik \
  --tools-root /workspaces/atrinik/workspace/worktrees/tools/syntax-decision-base \
  --profile syntax-decision \
  --state syntax-benchmark \
  --output build/authored-syntax-baseline.json
cmp build/authored-syntax-baseline.json \
  prototypes/authored-syntax-v1/measurement-baseline.json
```

The final `cmp` is expected to differ because timings and capture time are new;
compare schema, input commits/digests, selected maps, sample populations, and
distributions rather than demanding identical wall-clock observations.

For the wrapper-native server lifecycle used to validate the dependency:

```sh
cd /workspaces/atrinik
./atrinik topology show syntax-decision --service server --json
./atrinik build server --profile syntax-decision --test
./atrinik run server --profile syntax-decision --state syntax-benchmark -- \
  --content_benchmark=/shattered_islands/world_5_65_2,/shattered_islands/world_-4_65,/shattered_islands/world_-8_54,/shattered_islands/strakewood_island/greyton/house/luxury_house_0_0 \
  --content_benchmark_iterations=9
./atrinik up --name syntax-decision-runtime --profile syntax-decision \
  --state syntax-benchmark --service server
./atrinik ps syntax-decision-runtime
./atrinik logs syntax-decision-runtime server
./atrinik down syntax-decision-runtime
```

Expected results are clean exact `content`, `libatrinik`, `protocol`,
`resources`, and `server` dependency entries, 33 passing server tests, complete
version-1 benchmark records, a running supervised server with normal startup
logs, and no remaining topology processes after `down`. Profile-listed
components outside the server dependency set do not enter the measurements.
The isolated `syntax-benchmark` state is a prerequisite; do not point this
workflow at a mutable development or production state.

## Consequences and next work

Issue #15 should define typed, closed, versioned JSONC schemas and generate
shared field/reference metadata. It must cover every #17 field without turning
the physical-record scaffold into the semantic schema. Issue #14 should build
the single lossless core, targeted serializer, safe transactional CLI, and a
representative migrated consumer. Stable IDs and references continue to follow
issue #19.

Migration must remain dual-path until parity is demonstrated. A classic parser
may be removed only after the complete #17 rules and malformed corpus pass
through the shared implementation and downstream consumer tests. This decision
does not relax that gate.
