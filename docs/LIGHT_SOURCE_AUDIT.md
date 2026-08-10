# Effective light-source audit

Classic lighting resolves `glow_radius` and `light_color` from an archetype and
then applies map-instance or artifact overrides. Searching for literal fields
therefore misses inherited emitters and can count disabled overrides as active.
The `lights` world-content audit uses the shared lossless content core to resolve
that effective state:

```sh
python3 tools/world_content_audit.py lights > build/light-sources.json
python3 tools/world_content_audit.py lights --check
```

The JSON inventory records every nonzero archetype, artifact, and map-instance
emitter with its source path, exact source identity, map line and coordinates,
effective radius and color, face, visible/invisible classification, review
disposition, and rationale. Output is deterministic and source paths remain
repository-relative.

`maps/light-source-review.json` is the checked review baseline. It owns:

- the small RGB palette and the art-direction reason for each color;
- an intentional-neutral fallback and rationale for every emitting archetype
  and artifact, while authored effective fields identify explicit colors;
- one contextual review record for every map containing an effective emitter;
- a semantic SHA-256 for every source and map (including sorted effective
  emitter provenance, positions, radii, colors, faces, and visibility);
- a separate durable Classic client evidence manifest whose committed contact
  sheets, exact content/Classic client/Classic server/resources inputs,
  inventory digest, map semantic digests, viewport coordinates, lighting modes,
  and artifact SHA-256 values are all checked locally; and
- checks for overlaps, linked depths, horizontal boundaries, dark interiors,
  outdoor transitions, fog/roofs, and navigation cues.

The current baseline covers 89 emitting archetypes, two emitting artifacts, and
11,345 effective instances across 623 maps. Of those map instances, 5,878 are
invisible map-local composition lights. Invisible fill remains intentionally
neutral: adding one shared tint would recolor unrelated rooms and destroy the
mapper-authored balance where several radii overlap. Visible fire, lava,
lanterns, candles, crystals, cold/electrical/holy effects, and colored
forcefields, fungi, fairies, water, and portals instead inherit an explicit
six-digit color matched to their art. Visible map-local illumination on
non-emissive scenery and characters has a source-specific neutral rationale.

## Review and regeneration

Review the full generated inventory before changing the baseline. A new or
removed emitter, map, or artifact makes `--check` fail closed. Changes to an
existing emitter's effective source, position, radius, color, face, visibility,
or map context also invalidate its semantic digest. Do not refresh a digest or
copy an old disposition without opening the map in a current Classic render.

For this baseline, the wrapper profile `issue-65-light-colors` selected the
issue's `content-1x` worktree and the isolated `issue-65-lighting` scenario.
The Classic client at the commit recorded in
`maps/light-source-evidence/manifest.json` connected to that profile, enabled
its default smooth RGB renderer, teleported an invulnerable review character
to the recorded coordinates, and saved the primary map surface with
`/screenshot map`. A greedy 17-by-17 viewport cover produced at least one
smooth runtime view around every invisible emitter; maps without an invisible
emitter retain a representative view. Selected scenes were rendered again with
smooth lighting disabled so both client lighting paths cover every contextual
review criterion.

`maps/light-source-evidence/` commits those views as numbered 5-by-5 contact
sheets. The evidence manifest maps every tile back to its map semantic digest,
coordinates, and lighting mode. `lights --check` re-hashes each sheet, verifies
its encoded dimensions, rejects stale or duplicate tiles, checks the aggregate
inventory digest, and proves that every invisible emitter lies inside a
recorded smooth viewport. This makes the rendered pixels retrievable while
keeping generated full-resolution screenshots out of authored content.

When refreshing the review:

1. regenerate the inventory and inspect all new or changed rows;
2. render affected maps with the Classic client and a profile selecting the
   exact content worktree, retaining a 17-by-17 view around every invisible
   emitter;
3. compare overlaps and adjacent/depth-linked scenes in both smooth and
   discrete lighting where a color changes;
4. rebuild the affected contact sheets and evidence-manifest tiles, then
   update only the affected palette and review records; and
5. run `python3 tools/validate.py` and `git diff --check`.

The baseline is a review contract, not a second parser, renderer, or generated
runtime artifact. Runtime collection continues to use authored fields; the
audit only proves that each effective emitter has an intentional disposition.
