# Contributing

Choose `main`, `1.x`, or two linked pull requests before editing. Branch
ownership, backport labels, conflict handling, and release safety rules are in
[`docs/RELEASE_LINES.md`](docs/RELEASE_LINES.md). Never merge `main` wholesale
into `1.x` after formats diverge.

Open changes through a pull request whose title uses Conventional Commits
style. Preserve nearby `LICENSE` files and update attribution whenever an asset
is added, replaced, renamed, or moved. Do not assume a neighboring asset's
license applies without evidence.

Run `python3 tools/validate.py` before submitting a change. Generated collection
output is ignored and must not be committed.
