# Authoritative authored-content schema

`schemas/authored-content-v1/source.json` is the single declarative authority
for typed authored fields. It closes the field surface discovered by the v1
legacy grammar contract, defines the parser-neutral logical document consumed by
future loaders and editors, and reserves fields needed by registered server
features. Generated files in the same directory are projections, not additional
sources of truth.

This contract describes logical content. It does not parse legacy ADS or the
selected JSONC surface, replace the stable identity catalog, or prescribe an
in-memory server object layout.

## Contract layers

The schema composes three existing contracts:

- `contracts/content-v1/grammar-inventory.json` supplies the exact legacy map
  header and object-field vocabulary. Loading the schema fails if either list or
  the tiled-map field pattern drifts.
- `docs/AUTHORED_SYNTAX_DECISION.md` supplies encoding, duplicate-key, numeric,
  depth, collection, and string limits. Logical validation applies those same
  fail-closed limits before walking a decoded document.
- `docs/CONTENT_IDENTITIES.md` supplies domain-qualified persistent identities.
  References name an allowed identity domain rather than a path, display label,
  ordinal, or runtime table slot.

The declarative source groups current map-header and object properties by value
kind, assigns semantic roles, adds field-specific and role-wide bounds, records
reference domains, and describes the logical tree. It also distinguishes three
field states:

- `active` fields are accepted standard properties;
- `legacy-ignored` fields are known compatibility records retained until the
  legacy migration removes them; and
- `reserved` fields have an owning feature but do not yet expand the accepted
  legacy vocabulary.

A name absent from those sets is an error when presented as a standard
property. Extension data must instead use a `custom-property` record with an
explicit non-reserved namespace and portable name. Custom values are preserved
as bounded JSON values. The `atrinik` namespace is reserved for future standard
evolution, so a plugin cannot make an unknown field look standard.

## Logical document model

The generated `logical-document.schema.json` is JSON Schema Draft 2020-12. It
defines closed `map` and `archetype` documents independent of parser node types
or physical filename suffixes.

Map documents contain an ordered header and an ordered body of placed objects.
Archetype documents contain ordered logical definitions, each with a primary
object and zero or more ordered multipart objects. Object bodies preserve
comments, messages, properties, and recursively nested inventory objects in
authored order. Every order-bearing node and record carries a byte-based source
span with one-based line and column information. A source SHA-256 identifies the
physical input from which the logical document was decoded.

Schema validation checks closed shapes and typed values. The semantic validator
additionally rejects reversed or escaping spans, out-of-order records, duplicate
standard or custom properties, duplicate archetype logical IDs, incorrect
placed/nested/multipart contexts, and hostile trees beyond the selected parser
limits. A future parser adapter must emit this shape and retain its own concrete
syntax tree separately if it needs byte-perfect rewriting.

`dump_logical_document()` exposes a deterministic, sorted UTF-8 JSON encoding
after validation. `load_logical_document()` applies the same bounded numeric,
string, collection, depth, duplicate-key, and non-finite-value rules before
schema validation. Their round-trip tests include structured custom data and
source spans, demonstrating that intentional extension properties survive the
consumer interchange boundary unchanged.

## Generated projections

Run the generator after editing `source.json`:

```sh
python3 -m tools.content_schema generate --root .
python3 -m tools.content_schema validate --root .
```

The fixed output inventory is:

| File | Consumer purpose |
| --- | --- |
| `FIELDS.md` | Reviewable complete field inventory |
| `field-metadata.json` | Loader, compiler, checker, and migration metadata |
| `editor-properties.json` | Labels, widgets, ordering, constraints, and reference pickers |
| `field-ids.h` | Collision-checked C dispatch constants |
| `logical-document.schema.json` | Parser-neutral interchange validation |

Every output embeds the source digest where its format permits. Generation is
deterministic, writes only the fixed inventory through atomic replacement, and
rejects symbolic links in both inputs and output parents. The CI `check` command
renders everything in memory and byte-compares it with the committed files, so
manual edits and generator drift fail.

The C constants are FNV-1a hashes of domain-qualified field IDs. They make
generated dispatch tables stable when fields are inserted or reordered, and
generation fails on zero or a collision. They are local compiler/loader
constants, not save-format or wire-protocol identities; persisted data must use
the textual field ID.

## Legacy coverage and extensions

The corpus audit feeds every current archetype and map through the locked v1
grammar inspection boundary, validates values against their generated type and
bounds, and fails on any unexplained property. It scans without following
symbolic links. Run it directly for a deterministic summary:

```sh
python3 -m tools.content_schema audit --root . --json
```

Ten records observed outside the standard loader field tables have explicit
migration ownership rather than an implicit unknown-field exemption:

| Legacy record | Typed custom ID | Disposition |
| --- | --- | --- |
| `Wis` | `legacy.wisdom` | Remove after migration |
| `faction` | `server.faction` | Migrate |
| `faction_kill_penalty` | `server.faction_kill_penalty` | Migrate |
| `faction_rep` | `server.faction_rep` | Migrate |
| `notification_action` | `server.notification_action` | Migrate |
| `notification_delay` | `server.notification_delay` | Migrate |
| `notification_message` | `server.notification_message` | Migrate |
| `notification_shortcut` | `server.notification_shortcut` | Migrate |
| `spawn_time` | `server.spawn_time` | Migrate |
| `stock` | `script.merchant.stock` | Migrate |

The audit requires every mapping to occur in the current corpus, preventing a
stale exception from silently becoming permanent. Removal of the last authored
use and its mapping should therefore happen in the same migration.

## Registered feature fields

Fields requested by container capacity, spell encumbrance, item rarity,
tool/activity/resource/recipe definitions, and the specialization graph are
registered with types, constraints, domains, and owning issues. Registration
prevents each consumer from inventing incompatible spelling or metadata while
keeping the current legacy grammar closed. Change a reserved field to active
only with its consumer and authored-content migration.

The legacy editor XML and server loader tables remain temporary duplicates until
their consumers adopt generated projections. Do not edit generated metadata to
match those copies. Reconcile the declarative source, regenerate, migrate the
consumer, and remove the obsolete table when the migration issue permits it.

## Change policy

Treat `source.json`, its generator, and its committed projections as one atomic
contract change. Add or rename a standard field only with its value kind,
context, roles, constraints, reference domains, consumer ownership, tests, and
migration plan. Stable field renames require an explicit compatibility mapping;
changing an editor label or physical file path does not rename a logical ID.

The complete repository validation is:

```sh
python3 -m tools.content_schema validate --root .
python3 tools/validate.py
python3 tools/build_runtime.py --output build/runtime
git diff --check
```
