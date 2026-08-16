# Content grammar contracts and parity corpus

Atrinik's legacy authored-data syntax (ADS) is consumed by several independent
loaders, writers, checkers, collectors, and analyzers. The versioned contract at
`contracts/content-v1/` records their current boundary before any consumer is
replaced. It is the compatibility input for a future shared lossless core; it is
not a new production parser and does not change server behavior.

Run the complete contract validation from the repository root:

```sh
python3 -m tools.content_contracts validate --root .
python3 tools/validate.py
```

For a read-only, machine-readable characterization of a corpus-style map or
archetype file, run:

```sh
python3 -m tools.content_contracts inspect --root . --format map \
  contracts/content-v1/corpus/fixtures/nested-inventory.map
```

The inspector accepts only a regular file below the repository root, caps input
at 1 MiB, rejects NUL and invalid UTF-8, and never writes the input. It reports
block topology and representation facts needed by the corpus. It must not become
an authored-content loader, writer, checker, or normalizer.

## Grammar authority

The active server is authoritative for the accepted legacy grammar:

- `atrinik/server:src/loaders/object.l` defines object records, nested inventory,
  messages, known fields, extension fields, and the ten-entry FILE line-mode
  object stack. Its buffer and NUL-string entry points recurse without that
  explicit grammar bound.
- `atrinik/server:src/loaders/map_header.l` defines the map header and its
  mode-dependent behavior.
- `atrinik/server:src/loaders/object.l#get_ob_diff` defines object serialization.
- `atrinik/server:src/server/map.c#new_save_map` defines map serialization.

`grammar-inventory.json` captures those source locations, 291 known object
fields, the map-header fields and tiled-map key pattern, object and header
delimiters, all four object scanner entry modes, both map-header scanner entry
modes, the three observable load flags, byte/line-ending behavior, and the
required corpus features. The source files above remain authoritative if a
discrepancy is found;
the inventory and corpus must then be corrected together with a regression test.

The grammar is byte-oriented in the C loaders. Server Flex scanners are ASCII
case-insensitive and accept LF or CRLF for object records, while the map loader's
initial `arch map` sentinel and several legacy tools have stricter representation
assumptions. Server writers normalize output to LF. These differences are
intentional characterization data, not permission to normalize authored input.

Unknown object keys are server-supported extension data and must survive a
lossless round trip. Unknown map-header keys differ: the server logs and ignores
each record while some legacy checkers retain it. Consumers must surface this
representation disagreement instead of silently choosing one interpretation.

## Consumer inventory

`consumer-inventory.json` is the non-duplicated ownership inventory for every
identified grammar-facing component. It records source locations, repository,
role, format surface, current status, observable behavior, and the parity result
required before migration.

The inventory covers:

- authoritative server archetype, artifact, map, object, region, treasure, and
  player-save loaders plus the map and object writers;
- the content catalog, resource/runtime collectors, interface compiler, and the
  read-only world-content audit;
- the classic map checker, map-checker-qt, mapset, worldviewer, historical map-
  maker packager, and the superseded external Gridarta editor;
- the duplicate tools snapshot of the world-content audit, which is identified
  explicitly so it cannot be mistaken for another authority.

Collectors that copy authored files without parsing them are included because
byte preservation is part of the boundary. The client, protocol schemas,
standalone editor shell, and server random-map parameter reader were reviewed as
non-consumers: they do not parse or write this map/nested-object grammar.

When a consumer is added, removed, or changes observable ADS behavior, update
this inventory and its characterization before changing the implementation. A
later shared-core migration must use this file rather than creating another
consumer survey.

## Interchange schemas

The five JSON Schema Draft 2020-12 documents under `schemas/` define the stable
interchange boundary:

- `diagnostic` — structured severity, code, message, primary location, and
  related locations;
- `inspection` — document bytes and representation, ordered nodes and fields,
  comments, extension fields, and diagnostics;
- `patch` — conflict-detecting base/result digests and ordered, non-overlapping
  byte-range operations with base64 replacement bytes;
- `error` — machine-readable operation failure with retryability and diagnostics;
- `semantic-comparison` — equivalence, explicitly ignored representation traits,
  and structured semantic differences.

All root objects are closed. Paths are repository-relative and confined; digests
are lowercase SHA-256 values; patch insertions have empty source ranges; deletion
payloads are empty; and semantic equivalence must agree with the difference list.
Each schema has exactly one committed example in `examples/manifest.json`.

The dependency-free validator implements only the closed schema subset used by
these documents and fails on unknown schema keywords. This keeps baseline CI
self-contained while the JSON Schema files remain the portable public contract.

## Lossless parity corpus

`corpus/manifest.json` records 14 deterministic fixtures. Regular fixture files
cover comments and custom fields, multiline messages, multipart archetypes,
nested inventory, stable spell/skill identities, tiled maps, exits, stacked
objects, attribution, and malformed headers/messages/nesting. Inline base64
fixtures preserve exact CRLF, mixed line endings, and missing-terminal-newline
bytes without relying on checkout newline conversion.

Each entry pins the exact source SHA-256, applicable load modes, expected
structural observation, feature tags, and reviewed acceptance baselines for the
server and classic map checker. Validation requires the fixtures collectively to
cover every inventoried mode: `MAP_ARTIFACT`, `MAP_ORIGINAL`, `MAP_STYLE`, direct
Flex-buffer recursion, FILE line mode, NUL-string recursion, the object single-
variable API, the exact-sentinel map-header scanner, and its single-variable API.
The malformed and representation-sensitive cases deliberately record where those
consumers disagree. The validator requires the manifest and feature coverage to
remain canonical, validates every generated inspection and diagnostic against the
schemas, applies an empty conflict-detecting patch bound to each fixture digest,
and verifies the regular fixture's digest and modification time before and after
inspection. A no-op characterization is therefore byte-identical at both the
in-memory patch and filesystem boundaries.

The baselines are source-characterization snapshots, not claims that the legacy
executables run in content CI. When an executable baseline is deliberately
changed, update the authoritative consumer first, reproduce its result, update the
manifest, and explain the compatibility decision in the same pull request.

The attribution fixture has an adjacent `LICENSE`; moving or replacing it must
preserve the nearest-license rule used throughout this repository.

## Versioning and migration rules

Version 1 is additive only when existing consumers can safely ignore the new
data. Changing a required key, field meaning, byte-range semantics, grammar
interpretation, or established baseline requires a new version directory and new
schema IDs. Keep the old version while any supported consumer still depends on
it.

No legacy parser or writer may be deleted solely because these contracts exist.
A replacement must demonstrate, fixture by fixture:

1. identical bytes for a no-op load/save path;
2. matching inspection and diagnostics for accepted and malformed input;
3. an explicitly reviewed semantic comparison for any intentional normalization;
4. conflict-safe patch behavior against changed source bytes; and
5. migration of every applicable consumer-inventory entry.

The shared-core work consumes this contract, inventory, and corpus as-is. It must
not duplicate their surveys or weaken the recorded disagreements to simplify an
implementation.
