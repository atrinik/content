# Contributing

`main` is the sole authored and released content source. The `1.x` line is
immutable rollback and migration evidence at its final Semantic Release
coordinate; it is not a supported delivery target. Historical tags, releases, assets,
checksums, licenses, attribution, and parity records remain preserved. Do not
recreate a maintenance line or change its governance without a new explicit
organization-owner decision. Release ownership and recovery boundaries are in
[`docs/RELEASE_LINES.md`](docs/RELEASE_LINES.md).

Open changes through a pull request whose title uses Conventional Commits
style. Use a full GitHub issue URL for nonclosing cross-repository references;
reserve `owner/repository#number` shorthand for explicit closing lines so
Semantic Release does not report an unrelated issue as closed. Preserve nearby
`LICENSE` files and update attribution whenever an asset is added, replaced,
renamed, or moved. Do not assume a neighboring asset's license applies without
evidence.

Run `python3 tools/validate.py` before submitting a change. Generated collection
output is ignored and must not be committed.

Release automation installs the development dependencies from `package-lock.json`
with `npm ci` and invokes the local Semantic Release CLI with `npm run release`.
Use the Node.js version in the release workflow when changing this tooling, and
run `node scripts/release/test-release-policy.cjs` and
`node scripts/release/test-release-safety.cjs` to check release behavior. Preserve
the ordinary npm lockfile so dependency review and Dependabot can inspect updates.

The release toolchain includes npm's bundled dependencies. The npm 11.21.1
lock update fixes the bundled `postcss-selector-parser` finding, but its
`undici` 6.29.0 and `minimatch` 10.2.5 remain affected by
[Undici advisories](https://github.com/advisories/GHSA-2m5v-pch6-74hx) and
[the minimatch advisory](https://github.com/advisories/GHSA-g3hv-75wg-m249).
Track a compatible npm parent release containing Undici 6.29.1 or later and
minimatch 11.0.1 or later; npm 12.2.1 still bundles the same affected versions.
Do not treat this partial update as resolving those findings or force a
minimatch major override across npm's declared consumer ranges.
