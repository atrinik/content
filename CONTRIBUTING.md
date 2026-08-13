# Contributing

`main` is the sole authored and released content source. The `1.x` line is
immutable rollback and migration evidence at its final Semantic Release
coordinate; it is not a supported delivery target. Historical tags, releases, assets,
checksums, licenses, attribution, and parity records remain preserved. Do not
recreate a maintenance line or change its governance without a new explicit
organization-owner decision. Release ownership and recovery boundaries are in
[`docs/RELEASE_LINES.md`](docs/RELEASE_LINES.md).

Open changes through a pull request whose title uses Conventional Commits
style. Preserve nearby `LICENSE` files and update attribution whenever an asset
is added, replaced, renamed, or moved. Do not assume a neighboring asset's
license applies without evidence.

Run `python3 tools/validate.py` before submitting a change. Generated collection
output is ignored and must not be committed.
