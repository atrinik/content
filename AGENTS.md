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
- `schemas/authored-content-v1/source.json` is the authoritative typed field and
  logical-document source. Edit it rather than generated `FIELDS.md`, JSON, or C
  header projections; then run `python3 -m tools.content_schema generate --root
  .`. Keep types, roles, constraints, reference domains, consumer ownership,
  documentation, and migrations synchronized. Unknown standard fields must fail;
  extension data uses an explicit non-reserved custom namespace.
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
- `tools/content_core` is the production lossless parser, typed source view,
  project index, and targeted writer for legacy maps and archetypes. New content
  analyzers and editors must consume it instead of adding another ADS parser.
  Keep `schemas/content-core-v1`, CLI output, transaction preconditions, safety
  rules, Linux/Windows tests, and `docs/CONTENT_CORE.md` synchronized. Writes are
  dry-run-first and limited to authored source roots and `arch/*.arc` or `maps/`
  targets; never weaken digest/fingerprint checks or output/runtime refusals.
- `provenance/m1` is the fail-closed clean-room behavior and reusable-material
  boundary pinned to the `v1.8.1` main/1.x fork. Regenerate it only from a
  complete Git history with `python3 tools/m1_foundations.py generate --root
  .`. A behavior assignment is not permission to copy GPL Python. Only exact
  ID/digest rows in a package allowlist may cross into replacement owners, and
  every historical MIT grant row must cite the root registry revision and
  preserve the unchanged 1.x copy and terms.
- Trace every changed map path, archetype, animation, image, artifact, treasure,
  faction, interface, and script reference. Do not mask missing references with
  absolute paths, generated placeholders, or duplicated parsers.
- Generated runtime collection belongs under `build/` or another isolated
  output directory, never in source. Do not overwrite mutable server state.
- `main` is the sole forward authoring line and publishes explicit target
  artifacts. Use `python3 tools/build_runtime.py --target classic` for the
  schema-2 `classic-ads-v1` target; it remains `replacement_ready: false` and
  does not authorize replacement consumers to execute Classic-only GPL Python.
- `main` is the sole authored and released source. The `1.x` line is immutable
  rollback and migration evidence, not a supported delivery target.
  Preserve its final tags, releases, assets, checksums, licenses, attribution,
  parity ledger, and reachable history. Recreating maintenance requires a new
  explicit organization-owner decision.
- `tools/world_content_audit.py` is a read-only exploratory report. It may reveal
  review targets but never replaces `tools/validate.py` or the catalog, and its
  output is not generated source. Its map/archetype traversal must use the
  common lossless core. The checked main-line light review must preserve its
  pinned Classic decisions and replacement-runtime boundary, carry no Classic
  capture artifacts, and pass `python3 tools/world_content_audit.py lights
  --check` with zero unreviewed emitters.
- Run `python3 tools/validate.py` and `git diff --check` for every change. The
  aggregate validator already runs contracts, schema/syntax/catalog checks,
  lossless-core tests/audit, provenance/license gates, and an isolated runtime
  build. Run focused commands or the read-only world audit only when relevant;
  use wrapper builds/topologies for gameplay verification.
- Commits and pull-request titles use Conventional Commits. Every squash merge
  is released by semantic-release.
- Historical `1.x` releases remain immutable. Live ruleset removal and exact
  branch deletion belong only to the separately authorized governance gate.
- Preserve unrelated work and finish with `git diff --check`.
- Update this and any nested `AGENTS.md` in the same change when major rework
  alters content ownership, layout, identities, collection, or validation.
