# Authored content identities

`tools/content_catalog/` is the shared identity and cross-reference layer for
authored gameplay content. It reads authoritative sources directly; it is not
another source of truth. Run it from the repository root with:

```sh
python3 -m tools.content_catalog validate --root .
python3 -m tools.content_catalog emit --root . \
    --output build/content-catalog.json
```

The emitted JSON is deterministic, contains repository-relative source
locations, and belongs under `build/`. Collection runs the same validator
before writing any aggregate file. `python3 tools/validate.py` runs the catalog
unit tests and complete validation before building an isolated runtime tree.
The catalog fails closed when required authored roots are missing or contain
symbolic links. `emit` does not replace its output when validation fails and
publishes successful JSON atomically.

Stable IDs are domain-qualified at persistence and interchange boundaries,
for example `quest:lost_memories`, `quest-part:lost_memories::helping_out`,
`region:incuna`, `map:/shattered_islands/world_1_80`, and
`archetype:skill_literacy`. A matching string in another domain never satisfies
a typed reference.

| Domain | Canonical stable key | Authoritative source |
| --- | --- | --- |
| `archetype` | Primary `Object` key; multipart continuation objects are not independently addressable | Authored `arch/**/*.arc` files |
| `artifact` | `artifact` key | Authored `arch/**/*.art` and `maps/**/*.art` files |
| `treasure` | `treasure` or `treasureone` key; this is also the stable key for a reward backed by a treasure table | Authored `arch/**/*.trs` and `maps/**/*.trs` files |
| `map` | Leading-slash path relative to `maps/`, without rewriting the filename | Authored map file |
| `region` | `region` key | `maps/regions.reg` |
| `faction` | `faction` key | Authored `maps/**/*.factions` files |
| `quest` | Directory name immediately below `maps/interfaces/quests/` | `maps/interfaces/quests/<quest>/` |
| `quest-part` | Quest key plus nested part UIDs joined with `::` | The quest XML's `part uid` attributes |
| `spell` | Spell archetype key, conventionally `spell_<name>` | Type-29 spell archetype in `arch/`; the server maps it to a runtime index |
| `skill` | Skill archetype key, conventionally `skill_<name>` | Type-43 skill archetype in `arch/`; the server maps it to a runtime index |
| `npc` | Explicit `id` | `maps/content-identities.json` |
| `property` | Explicit `id` | `maps/content-identities.json` |

Display names, messages, descriptions, translations, filesystem enumeration
order, C enum values, and array positions are not identities. Quest-part UIDs
are validated and preserved verbatim; the interface compiler must never
sanitize one into a different key. Runtime spell and skill indices are
process-local acceleration values. Durable consumers serialize the stable
archetype key and resolve it after startup.

Interfaces bind these identities with `npc_id` and `property_id`. Interface
compilation uses `npc_id` for its output filename, and map events point to that
stable handler; `npc` remains only the visible Classic name. This keeps
dispatch stable when a display name changes.

Existing monster variants and bosses retain their archetype identities; do not
invent parallel variant or boss IDs for them. A monster-family key does not yet
have an authoritative authored source. The same is true for disciplines,
techniques, activities, achievements, and named landmark records. The feature
that introduces one of those concepts must add its explicit key to its owning
authored schema and teach the catalog loader about that schema in the same
change. A monster's mutable `name` or broad `race` value is not a safe
substitute. Alchemical formulae likewise have no current authored entries or
stable recipe key; the first recipe work must add an explicit recipe key rather
than deriving one from its result title or ingredient order.

The existing quest-interface `cast` attribute contains a spell display name.
The catalog validates its current conventional mapping to a `spell_*` key, but
the attribute is not a durable typed identity and must not be persisted or
exchanged as one. Replacing it with an explicit `spell_id` requires a
coordinated interface-schema, compiler, and server-consumer change.

## Rename, removal, and migration policy

Before any ID has a durable consumer, a rename may be made atomically by
updating its authoritative definition and every in-repository reference. Once
an ID has been persisted or exchanged externally, its rename or removal must
include a reviewed migration or tombstone owned beside that domain's source.
The migration must identify the old domain-qualified key, the replacement (or
explicit removal), and every durable store that applies it. Tests must cover
both resolution and repeated application.

Do not add aliases or migrations for hypothetical data. Generated catalogs and
runtime lookup tables are rebuilt from the post-migration sources and are never
edited by hand. A migration may be deleted only when every supported store has
recorded its application and no accepted input can still contain the old key.
