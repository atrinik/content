# Contributing

This `1.x` branch is immutable rollback and migration evidence. It is not an
authored source, maintenance line, or release channel. `main` is the sole
authored and released content source. Preserve the final tags, releases,
assets, checksums, licenses, attribution, parity records, and reachable history.
Do not add authored changes or restore Semantic Release. Emergency recreation
or maintenance requires a new explicit organization-owner decision. Historical
recovery boundaries are in
[`docs/RELEASE_LINES.md`](docs/RELEASE_LINES.md).

Open changes through a pull request whose title uses Conventional Commits
style. Preserve nearby `LICENSE` files and update attribution whenever an asset
is added, replaced, renamed, or moved. Do not assume a neighboring asset's
license applies without evidence.

Run `python3 tools/validate.py` before submitting a change. Generated collection
output is ignored and must not be committed.
