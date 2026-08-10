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
- the Classic worldmaker batch used to inspect the rendered scene, its PNG
  SHA-256, and exact content/server/resources/profile inputs; and
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
issue's `content-1x` worktree. `./atrinik build server --profile
issue-65-light-colors --test` ran the Classic server tests and worldmaker. Its
stitched region images covered outdoor boundaries and linked world/depth
layouts; focused temporary worldmaker roots rendered disconnected interiors
individually. Those temporary roots were review inputs only and are not
authored content. The baseline retains the exact renderer commits/settings and
SHA-256 of every reviewed PNG so regenerated evidence can be checked without
committing generated images.

When refreshing the review:

1. regenerate the inventory and inspect all new or changed rows;
2. render affected maps with a profile selecting the exact content worktree;
3. compare overlaps and adjacent/depth-linked scenes in both smooth and
   discrete lighting where a color changes;
4. update only the affected palette and review records; and
5. run `python3 tools/validate.py` and `git diff --check`.

The baseline is a review contract, not a second parser, renderer, or generated
runtime artifact. Runtime collection continues to use authored fields; the
audit only proves that each effective emitter has an intentional disposition.
