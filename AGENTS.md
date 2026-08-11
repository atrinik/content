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
- Trace every changed map path, archetype, animation, image, artifact, treasure,
  faction, interface, and script reference. Do not mask missing references with
  absolute paths, generated placeholders, or duplicated parsers.
- Generated runtime collection belongs under `build/` or another isolated
  output directory, never in source. Do not overwrite mutable server state.
- Branch `1.x` is the maintained classic content line. Its release contract is
  `contracts/release-lines/classic-1x.json`; runtime manifests must identify
  exact branch/commit, classic formats and consumers, licenses, and
  `replacement_ready: false`. Never merge replacement `main` wholesale into
  this branch or accept replacement-only formats/tooling.
- Assess every issue-driven authored-content fix against both `main` and `1.x`;
  a fix discovered on `1.x` must also reach `main` whenever compatible.
  Compatible shared fixes
  normally ship to both lines through separate worktrees, validation runs,
  commits, and linked pull requests. For paired delivery, the canonical `main`
  pull request is the only one that closes the issue; its `1.x` companion links
  both the issue and canonical pull request without using a closing keyword. A
  single-line exception must record explicit evidence and rationale explaining
  why the other line is unaffected or incompatible, such as replacement-only
  schemas or tooling, Classic-only formats or consumers, runtime
  incompatibility, or provenance or attribution constraints. The sole
  applicable pull request is canonical: a `main` pull request uses a closing
  keyword; a `1.x` pull request links without one, and the issue is closed
  manually after merge. Never merge branches wholesale or share generated
  output between worktrees. Port linkage and review rules are
  documented in `docs/RELEASE_LINES.md`.
- `tools/world_content_audit.py` is a read-only exploratory report. It may reveal
  review targets but never replaces `tools/validate.py` or the catalog, and its
  output is not generated source. Its map/archetype traversal must use the
  common lossless core.
- Run `python3 tools/validate.py` and `git diff --check` for every change. The
  aggregate validator already runs contracts, schema/syntax/catalog checks,
  lossless-core tests/audit, release-line/license gates, and an isolated runtime
  build. Run focused commands or the read-only world audit only when relevant;
  use wrapper builds/topologies for gameplay verification.
- Commits and pull-request titles use Conventional Commits. Every squash merge
  is released by semantic-release.
- `1.x` releases use semantic-release maintenance range/channel `1.x`. Because
  `main` owns the post-fork `v1.9.0` tag, this line can publish only patch
  versions in `>=1.8.1 <1.9.0`. Keep analyzer exceptions limited to the exact
  historical `feat(release)` bootstrap and seven pre-policy feature subjects
  documented in `docs/RELEASE_LINES.md`; do not weaken ordinary feature or
  breaking-change classification. The pull-request title policy rejects all
  new feature and breaking titles targeting `1.x`. Published releases and dry
  runs must stay in that range on channel `1.x`. Keep the GitHub plugin's
  failure-issue hook disabled so an issue-creation failure cannot obscure the
  original Semantic Release error in the workflow log.
- Preserve unrelated work and finish with `git diff --check`.
- Update this and any nested `AGENTS.md` in the same change when major rework
  alters content ownership, layout, identities, collection, or validation.
