# Effective light-source audit

Classic lighting resolves `glow_radius` and `light_color` from an archetype and
then applies map-instance or artifact overrides. Type-74 lights are toggleable:
their resting radius is zero, but applying one activates the radius stored in
`last_sp`. Searching for literal fields therefore misses inherited and
toggle-active emitters. The `lights` world-content audit uses the shared
lossless content core to resolve that effective state:

```sh
python3 tools/world_content_audit.py lights > build/light-sources.json
python3 tools/world_content_audit.py lights --check
```

The JSON inventory records every continuous or toggle-active archetype,
artifact, and map-instance emitter with its source path, object and field lines,
activation mode, map coordinates, effective radius and color, face,
visible/invisible classification, review disposition, and rationale. It also
records every archetype that supplies an effective color, even when a map
override supplies its radius. Output is deterministic and source paths remain
repository-relative.

`maps/light-source-review.json` is the checked review baseline. It owns:

- the small RGB palette and the art-direction reason for each color;
- an intentional-neutral fallback and rationale for every emitting archetype
  and artifact, while authored effective fields identify explicit colors;
- one art-specific rationale for every archetype supplying an effective color;
- one contextual review record for every map containing an effective emitter,
  plus source-line rationales for map-local face or animation substitutions;
- one reviewed semantic state and active-runtime evidence binding for every
  distinct type-74 radius/color/face/animation combination;
- a semantic SHA-256 for every source and map (including sorted effective
  emitter provenance, positions, radii, colors, faces, and visibility);
- a separate durable Classic client evidence manifest whose committed contact
  sheets, exact content/Classic client/Classic server/resources inputs,
  inventory digest, map semantic digests, viewport coordinates, lighting modes,
  and artifact SHA-256 values are all checked locally; and
- explicit pass records, rationales, and smooth/discrete evidence identifiers
  for overlaps, linked depths, horizontal boundaries, dark interiors, outdoor
  transitions, fog/roofs, and navigation cues.

The current baseline covers 97 emitting archetypes, four emitting artifacts,
121 effective color suppliers, 11 toggle-active semantic states, and 11,391
effective instances across 625 maps.
Of those map instances, 5,878 are invisible map-local composition lights.
Invisible fill remains intentionally neutral: adding one shared tint would
recolor unrelated rooms and destroy the mapper-authored balance where several
radii overlap. Visible fire, lava, lanterns, candles, crystals,
cold/electrical/holy effects, and colored forcefields, fungi, fairies, water,
and portals instead inherit an explicit six-digit color matched to their art.
Visible map-local illumination on non-emissive scenery and characters has a
source-specific neutral rationale.

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
review criterion. Every distinct toggle-active state was also created or
reached, applied, and captured in the isolated scenario. Those views record
the exact state ID and runtime command, proving active radius, color, face, and
animation instead of merely showing resting art.
Before ordinary smooth or discrete capture, the reviewer must emit no light and
all carried toggle lights must be explicitly extinguished and unapplied. The
evidence context records that clean player-state precondition so a test light
cannot tint unrelated map views. A linked-map viewport can render the same
reviewer representation more than once; this is acceptable only when the
scenario contains no second server-side player object or saved gravestone.

`maps/light-source-evidence/` commits 1,130 views as 46 numbered 5-by-5 contact
sheets. The evidence manifest maps every tile back to its map semantic digest,
coordinates, lighting mode, exact content input, and full-resolution capture
digest. `lights --check` re-hashes each sheet, validates all PNG chunks, CRCs,
compressed scanlines, filters, and dimensions, rejects stale, duplicate, or
unlisted artifacts, checks the aggregate inventory digest, proves that every
invisible emitter lies inside a recorded smooth viewport, and requires an
active view for every toggle state. A separate digest over all authored
`arch/` and runtime `maps/` inputs proves the final tree still matches the tree
used by the recorded content build even when review-only files are committed
after that build. The review JSON and evidence directory are
explicitly omitted from playable runtime collection, while remaining
available in the source tree for maintainers.

The checked generator makes viewport selection, tile order, and sheet encoding
reproducible. `plan` emits the greedy cover in map-path order. `build` consumes
ordered smooth/discrete capture manifests whose rows contain `artifact`, `map`,
coordinates, semantic/content bindings, and the capture digest; it creates
5-by-5 sheets in manifest order. Each 1024-by-768 client
PNG is nearest-neighbor sampled to 204 by 153 pixels, unused tiles remain black,
tile top/left edges are white, and output is deterministic RGB PNG using filter
zero and zlib level nine. Every raw-manifest row also supplies its capture
SHA-256, content commit, and current map semantic SHA-256; active rows add the
toggle-state ID and exact runtime command. `--dry-run` fully decodes and checks
all input captures. A real build renders into a sibling staging directory and
atomically replaces the evidence directory, so stale sheets and partial builds
cannot survive. Context and representative-check JSON objects use the same
shapes as those objects in the committed manifest:

```sh
python3 tools/light_review_evidence.py plan \
  --inventory build/light-sources.json > build/light-capture-plan.json
python3 tools/light_review_evidence.py build \
  --inventory build/light-sources.json \
  --smooth-manifest build/light-captures/smooth/manifest.json \
  --discrete-manifest build/light-captures/discrete/manifest.json \
  --context build/light-captures/context.json \
  --representatives build/light-captures/representatives.json \
  --output maps/light-source-evidence --dry-run
python3 tools/light_review_evidence.py build \
  --inventory build/light-sources.json \
  --smooth-manifest build/light-captures/smooth/manifest.json \
  --discrete-manifest build/light-captures/discrete/manifest.json \
  --context build/light-captures/context.json \
  --representatives build/light-captures/representatives.json \
  --output maps/light-source-evidence
```

When refreshing the review:

1. regenerate the inventory and inspect all new or changed rows;
2. render affected maps with the Classic client and a profile selecting the
   exact content worktree, retaining a 17-by-17 view around every invisible
   emitter;
3. activate and render every changed type-74 semantic state, and compare
   overlaps and adjacent/depth-linked scenes in both smooth and discrete
   lighting where a color changes;
4. use the checked plan/build commands to rebuild contact sheets and manifest
   tiles, then update only affected palette and review records; and
5. run `python3 tools/validate.py` and `git diff --check`.

The baseline is a review contract, not a second parser, renderer, or generated
runtime artifact. Runtime collection continues to use authored fields; the
audit only proves that each effective emitter has an intentional disposition.
