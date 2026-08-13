# Light-source audit

`object.light_color` is an exact six-digit RGB24 value. Uppercase and lowercase
hexadecimal digits are accepted; a missing value preserves the neutral-white
default. The field does not change radius, placement, obstruction, activation,
or gameplay visibility.

The checked [`maps/light-source-review.json`](../maps/light-source-review.json)
baseline covers every effective nonzero emitter. The inventory resolves
archetype inheritance, artifact clones, map overrides, invisible sources, and
toggle-active objects through the shared lossless content core. Each review row
pins the semantic digest of its effective fields and exact source locations, so
a new, removed, or changed emitter fails validation until it is deliberately
reviewed.

Schema version 6 also supports semantic `fixture_groups` for an authored
fixture family. A group pins its archetype set, default radii and color,
per-archetype placement counts, map coverage, intentional non-emitting members,
applicable contextual checks, and a digest of every resolved placement. These
checks are derived entirely from authored sources: fixture groups do not carry
view IDs or depend on screenshots, capture manifests, or image files.
Required families are anchored independently in
[`maps/light-source-fixture-contract.json`](../maps/light-source-fixture-contract.json).
The audit inventories the contract's archetypes even if the review row is
missing, and validation requires the exact contracted archetype and contextual
check sets. Removing a required ledger group therefore fails closed instead of
silently disabling its placement, non-emitter, or overlap checks.

The `magic-lantern-fixtures` group covers all 402 standing and wall-mounted
magic lanterns across 66 maps. Standing fixtures inherit radius 5 and wall
fixtures radius 7; map-local radius-3/4/5/6/7/9 fields preserve the established
heterogeneous compositions. The visible fixtures own their warm-gold sources,
so no neutral `light3`–`light9` helper remains co-located with a magic lantern.

Run the read-only inventory and acceptance check from the repository root:

```sh
python3 tools/world_content_audit.py lights > build/light-sources.json
python3 tools/world_content_audit.py lights --check
```

The first command exposes current source locations and semantic hashes for
review; the second requires a complete palette, rationales, contextual
decisions, exact row sets, current hashes, and zero unreviewed emitters. The
aggregate `python3 tools/validate.py` command runs the same check and excludes
semantic review ledger and required-fixture contract from playable runtime
packages.

## Review provenance and runtime boundary

The baseline palette and historical source contexts were reviewed on Classic
`1.x` in [PR #67](https://github.com/atrinik/content/pull/67) at commit
`958b557650252518b9ea2850200920d07c879bd2`. The main-line ledger preserves the
identifiers of those Classic views as historical provenance but does not
attribute later fixture-ownership or contextual decisions to that review, nor
copy its screenshots, capture manifest, proof scene, or Classic-only tooling.
Current fixture-group rationales and semantic hashes document those later
main-line decisions; associated pull requests summarize any optional Classic
smooth/discrete diagnostics performed for them.

The replacement stack does not yet provide integrated content build, runtime,
or renderer adapters. That boundary is tracked by atrinik/atrinik
[#266](https://github.com/atrinik/atrinik/issues/266),
[#269](https://github.com/atrinik/atrinik/issues/269), and
[#270](https://github.com/atrinik/atrinik/issues/270). Therefore main-line
validation proves authored/schema/catalog/semantic compatibility without
claiming that these colors are visually active. Classic must not be substituted
as replacement runtime verification.

## Updating a reviewed source

When an emitter changes, inspect its actual main-line archetype or map context
and the pinned Classic decision. Preserve or revise the color and rationale
intentionally; do not mass-color invisible or map-local lights by name or
radius. Update the matching ledger row with the semantic hash from the read-only
inventory, then run `python3 tools/world_content_audit.py lights --check` and
`python3 tools/validate.py`. Genuine replacement-specific divergences must be
documented rather than copied mechanically from `1.x`.

The base `power_crystal` and its six artifact variants inherit one radius-1
`fff0c0` source. Charge capacity, artifact upgrades, and multiple instances do
not alter that per-object radius or color. The deterministic Classic lifecycle
checks for ground, inventory, containment, trade, stronger-light precedence,
map transitions, logout/login, and death are retained as source-behavior
provenance in [`POWER_CRYSTAL_LIGHT_REVIEW.md`](POWER_CRYSTAL_LIGHT_REVIEW.md);
they do not claim integrated replacement-runtime verification.
