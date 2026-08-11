# Light-source audit

`light_color` is an exact six-digit RGB24 value. Uppercase and lowercase
hexadecimal digits are accepted; a missing value preserves the neutral-white
default. The field does not change radius, placement, obstruction, activation,
or gameplay visibility.

The checked [`maps/light-source-review.json`](../maps/light-source-review.json)
baseline covers every effective nonzero emitter. The inventory resolves
archetype inheritance, artifact clones, map overrides, invisible sources, and
toggle-active objects through the shared lossless content core. Each review row
pins the semantic digest of its effective fields and exact source locations, so
a new, removed, or changed emitter fails validation until it is deliberately
reviewed. Palette entries, source and map rationales, contextual decisions, and
the zero-unreviewed-emitter gate remain authored review requirements.

Run the read-only inventory and acceptance check from the repository root:

```sh
python3 tools/world_content_audit.py lights > build/light-sources.json
python3 tools/world_content_audit.py lights --check
```

The first command writes a generated diagnostic below the ignored `build/`
tree. The second requires complete row sets, current semantic hashes, palette
and contextual rationales, and zero unreviewed emitters. The aggregate
`python3 tools/validate.py` command runs the same check and excludes the
semantic review ledger from playable runtime packages.

## Rendered imagery is generated outside content Git

This repository does not track light-source screenshots, contact sheets, a
capture manifest, a proof scene, or screenshot-packing tooling. Durable world
imagery belongs to the build and deployment work tracked by content issues
[#4](https://github.com/atrinik/content/issues/4) and
[#125](https://github.com/atrinik/content/issues/125), plus website issue
[#34](https://github.com/atrinik/website/issues/34). Those pipelines must write
images and tiles below `build/` or another ignored output location, never below
the authored `maps/` tree.

The palette and contextual decisions originated in the Classic review delivered
by [PR #67](https://github.com/atrinik/content/pull/67). The semantic ledger
preserves those decisions and their source/map digests without retaining the
generated images or identifiers that bound rows to committed contact sheets.
Screenshot-refresh requirements in older lighting issue checklists are
superseded: semantic audit and normal repository validation remain mandatory,
while diagnostic rendering is optional and must remain generated output.

## Updating a reviewed source

When an emitter changes, inspect its archetype or map context and the existing
art-direction decision. Preserve or revise the color and rationale
intentionally; do not mass-color invisible or map-local lights by name or
radius. Update the matching ledger row with the semantic hash from the read-only
inventory, then run:

```sh
python3 tools/world_content_audit.py lights --check
python3 tools/validate.py
git diff --check
```

Optional Classic renderer inspection may inform that decision, but its captures
are not merge or release prerequisites and must not enter content Git status.
The ledger and audit never change archetypes, maps, light behavior, or packaged
runtime content.

The base `power_crystal` and its six artifact variants inherit one radius-1
`fff0c0` source. Charge capacity, artifact upgrades, and multiple instances do
not alter that per-object radius or color. The deterministic Classic lifecycle
checks for ground, inventory, containment, trade, stronger-light precedence,
map transitions, logout/login, and death are recorded in
[`POWER_CRYSTAL_LIGHT_REVIEW.md`](POWER_CRYSTAL_LIGHT_REVIEW.md).
