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

Run the read-only inventory and acceptance check from the repository root:

```sh
python3 tools/world_content_audit.py lights > build/light-sources.json
python3 tools/world_content_audit.py lights --check
```

The first command exposes current source locations and semantic hashes for
review; the second requires a complete palette, rationales, contextual
decisions, exact row sets, current hashes, and zero unreviewed emitters. The
aggregate `python3 tools/validate.py` command runs the same check and excludes
the review ledger from runtime packages.

## Review provenance and runtime boundary

The palette and contextual decisions were reviewed on Classic `1.x` in
[PR #67](https://github.com/atrinik/content/pull/67) at commit
`958b557650252518b9ea2850200920d07c879bd2`. The main-line ledger preserves the
identifiers of those Classic views as historical provenance but does not copy
their screenshots, capture manifest, proof scene, or Classic-only tooling.

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
