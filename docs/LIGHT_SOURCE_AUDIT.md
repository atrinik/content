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
  distinct type-74 activation archetype, radius, color, and clone-derived
  active face/animation combination;
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
121 effective color suppliers, 14 toggle-active semantic states, and 11,393
effective instances across 625 maps.
Of those map instances, 5,857 are invisible map-local composition lights.
Invisible fill remains intentionally neutral: adding one shared tint would
recolor unrelated rooms and destroy the mapper-authored balance where several
radii overlap. Visible fire, lava, lanterns, candles, crystals,
cold/electrical/holy effects, and colored forcefields, fungi, fairies, water,
and portals instead inherit an explicit six-digit color matched to their art.
Visible map-local illumination on non-emissive scenery and characters has a
source-specific neutral rationale.

### Glower fixture ownership

`glower.101` owns the reviewed warm `ffd080` color without a global radius.
Every placement records an explicit map-local radius, so the 21 fixtures that
replaced co-located neutral helpers preserve their scalar footprints and the
five independently reviewed fixtures remain non-emitting with radius zero:

| Context and map | Fixtures | Radius | Disposition |
| --- | ---: | ---: | --- |
| Greyton Jail `greyton/jail/jail` | 6 | 5 | migrated from six `light5` helpers |
| Old Outpost `old_outpost_a_0204` | 1 | 5 | migrated from one `light5` helper |
| Rockforge `rockforge_a_aa01` | 4 | 9 | migrated from four `light9` helpers |
| Rockforge `rockforge_a_ab01` | 8 | 9 | migrated from eight `light9` helpers |
| Asteria `world_3_45` | 1 | 7 | migrated from one `light7` helper |
| Mountain inn `world_7_64_1` | 1 | 4 | migrated from one `light4` helper |
| Asteria Docks `world_10_42_1` | 1 | 0 | explicitly non-emitting; no prior source |
| Brynknot `world_1_68` | 4 | 0 | explicitly non-emitting; no prior source |

The zero-radius placements still inherit the fixture color for a reproducible
future disposition, but Classic creates no light pool for them. No independent
ambient helper was removed outside the 21 exact same-tile pairs.

## Review and regeneration

Review the full generated inventory before changing the baseline. A new or
removed emitter, map, or artifact makes `--check` fail closed. Changes to an
existing emitter's effective source, position, radius, color, face, visibility,
or map context also invalidate its semantic digest. Do not refresh a digest or
copy an old disposition without opening the map in a current Classic render.

For this baseline, the wrapper profile `issue-103-glower-1x` selected the
issue's `content-1x` worktree at the source checkpoint recorded in the
manifest. The isolated topology and scenario were both
`issue-103-glower-lighting`, with state
`scenario-issue-103-glower-lighting`.
The Classic client at the commit recorded in
`maps/light-source-evidence/manifest.json` connected to that profile, enabled
its default smooth RGB renderer, teleported an invulnerable review character
to the recorded coordinates, and saved the primary map surface with
`/screenshot map`. A greedy 17-by-17 viewport cover produced at least one
smooth runtime view around every invisible emitter; maps without an invisible
emitter retain a representative view. Selected scenes were rendered again with
smooth lighting disabled so both client lighting paths cover every contextual
review criterion. Every effective archetype and artifact definition was
created in the review-only `tools/light-source-review/dark-lab` scene and bound
to its semantic digest and exact command. Continuous definitions use
`/screenshot map` and are compared with a clean map-surface control. Every
distinct toggle-active state was also created or reached, applied, and captured
beside a separate clean full-window control of that same scene. Toggle views
are full 1024-by-768 client frames rather than map-only exports so the applied
inventory art and its runtime light pool are both reviewable. Each view records
its capture surface, so map-only evidence cannot be compared with a full-window
control. Those views record the exact state ID, activation archetype, and
runtime command; the checker decodes the committed tiles and requires a
material light-pool difference from the matching control for every continuous
and toggle-active source. Changed pixels must extend beyond the largest actual
PNG canvas used by the speed-zero source face or active animation in both axes,
so oversized art, resting art, changed UI, or isolated sprite pixels cannot
satisfy the light-pool proof. It also rejects one raw capture reused by states whose effective
radius, color, face, animation, or visibility differs.
Before ordinary smooth or discrete capture, the reviewer must emit no light and
all carried toggle lights must be explicitly extinguished and unapplied. The
evidence context records that clean player-state precondition so a test light
cannot tint unrelated map views. A linked-map viewport can render the same
reviewer representation more than once; this is acceptable only when the
scenario contains no second server-side player object or saved gravestone.

`maps/light-source-evidence/` commits the generated views as numbered 5-by-5
contact sheets. The evidence manifest maps every tile back to its map semantic
digest or review-scene source digest, coordinates, lighting mode, exact content
input, definition/state bindings, and full-resolution capture digest.
`lights --check` re-hashes each sheet, validates all PNG chunks, CRCs,
compressed scanlines, filters, and dimensions, rejects stale, duplicate, or
unlisted artifacts, checks the aggregate inventory digest, proves that every
invisible emitter lies inside a recorded smooth viewport, and requires a
source-bound, control-compared view for every effective definition plus an
active view for every toggle state. A separate digest over all authored
`arch/` and runtime `maps/` inputs binds the renders to their recorded immutable
content commit. Current relevance is checked through the aggregate lighting
inventory, each bound map, source, and active-state semantic digest, and
`render_assets_sha256` over every resolved light-source PNG and animation file.
An unrelated authored-content change therefore does not require recapturing
every sheet, while same-size rendered-art changes still do. After a squash
merge, `runtime_content_commit` may name the merged commit, reachable from the
current history, whose runtime digest matches the original capture commit; the
original `content_commit` and per-view bindings remain unchanged as capture
provenance.
The review JSON, evidence directory, review-only lab, and generated Python
bytecode caches are explicitly omitted from playable runtime collection, while
the authored review inputs remain available in the source tree for maintainers.

The checked generator makes viewport selection, tile order, and sheet encoding
reproducible. `plan` emits the greedy cover in map-path order; `plan-sources`
emits the full-window toggle control, every archetype/artifact definition, any
remaining map-only active state, and the map-surface continuous control in
semantic order. `build` consumes
ordered smooth/discrete capture manifests whose rows contain `artifact`, `map`,
coordinates, semantic/content bindings, and the capture digest; it creates
5-by-5 sheets in manifest order. Each 1024-by-768 client
PNG is nearest-neighbor sampled to 204 by 153 pixels, unused tiles remain black,
tile top/left edges are white, and output is deterministic RGB PNG using filter
zero and zlib level nine. Every raw-manifest row also supplies its capture
SHA-256, content commit, and current map semantic SHA-256 or review-scene file
SHA-256. Source rows add source kind, identity, semantic digest, exact runtime
command, capture surface, and the matching surface-specific dark-control ID;
active rows also add the toggle-state ID. Classic's `/console` transport uses
one unmatched leading quote to preserve command whitespace; the generated
command intentionally has no closing quote. In an active transcript, the
semicolon before the second slash command separates two consecutive client
submissions; it is not entered as part of either command.
`--dry-run` fully decodes and checks all input captures. A real build renders
into a sibling staging directory and atomically replaces the evidence
directory, so stale sheets and partial builds cannot survive. Context and
representative-check JSON objects use the same shapes as those objects in the
committed manifest:

```sh
python3 tools/light_review_evidence.py plan \
  --inventory build/light-sources.json > build/light-capture-plan.json
python3 tools/light_review_evidence.py plan-sources \
  --inventory build/light-sources.json \
  --map tools/light-source-review/dark-lab --x 9 --y 9 \
  > build/light-source-capture-plan.json
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
3. stage `tools/light-source-review/dark-lab` only in the isolated server's live
   map root (for example, with
   `install -D -m 0644 tools/light-source-review/dark-lab "$ATRINIK_REVIEW_MAPS/light-source-review/dark-lab"`),
   teleport to `/light-source-review/dark-lab 9 9`, then create every changed
   source with the complete generated command transcript in order; retain `/screenshot map` for
   continuous rows and a full-client frame for type-74 rows, plus one clean
   control on each capture surface;
4. compare overlaps and adjacent/depth-linked scenes in both smooth and
   discrete lighting where a color changes;
5. use the checked plan/build commands to rebuild contact sheets and manifest
   tiles, then update only affected palette and review records; and
6. run `python3 tools/validate.py` and `git diff --check`.

The baseline is a review contract, not a second parser, renderer, or generated
runtime artifact. Runtime collection continues to use authored fields; the
audit only proves that each effective emitter has an intentional disposition.
