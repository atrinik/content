# Atrinik content repository guide

- This repository owns authored maps, archetypes, graphics, animations,
  artifacts, treasures, factions, XML interfaces, quests, and embedded content
  Python. Server/client implementation and the map-checker application remain
  in their standalone repositories.
- Read the nearest nested `AGENTS.md` under `arch/` or `maps/` before changing
  those trees. Preserve file layout, formatting, case, attribution, and
  per-asset licensing; avoid unrelated normalizer churn.
- `tools/content_catalog` is the authoritative identity and cross-reference
  layer. Persist domain-qualified stable IDs, not display names, filesystem
  ordering, or runtime table positions.
- `contracts/content-v1` owns the legacy ADS grammar/consumer inventory,
  interchange schemas, and lossless parity corpus. Preserve fixture bytes and
  update observations, baselines, documentation, and tests together whenever a
  loader, writer, checker, collector, analyzer, or grammar behavior changes. Do
  not treat the characterization inspector as a production parser.
- `docs/AUTHORED_SYNTAX_DECISION.md` and
  `prototypes/authored-syntax-v1/limits.json` own the selected strict JSONC
  surface and fail-closed machine limits. Keep the fixed baseline lock,
  prototype implementation digest, committed measurement evidence, decision
  text, and Linux/Windows tests synchronized. Do not promote the neutral
  physical-record comparison model into the final typed schema.
- Trace every changed map path, archetype, animation, image, artifact, treasure,
  faction, interface, and script reference. Do not mask missing references with
  absolute paths, generated placeholders, or duplicated parsers.
- Generated runtime collection belongs under `build/` or another isolated
  output directory, never in source. Do not overwrite mutable server state.
- `tools/world_content_audit.py` is a read-only exploratory report. It may reveal
  review targets but never replaces `tools/validate.py` or the catalog, and its
  output is not generated source.
- Run `python3 -m tools.content_contracts validate --root .`,
  `python3 -m tools.syntax_evaluation --root .`,
  `python3 tools/validate.py`, and
  `python3 tools/build_runtime.py --output build/runtime` for every change. Run
  the focused world audit when relevant and use wrapper builds/topologies for
  gameplay verification.
- Commits and pull-request titles use Conventional Commits. Every squash merge
  is released by semantic-release.
- Preserve unrelated work and finish with `git diff --check`.
- Update this and any nested `AGENTS.md` in the same change when major rework
  alters content ownership, layout, identities, collection, or validation.
