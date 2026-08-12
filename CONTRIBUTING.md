# Contributing

`main` is the sole forward authoring line. `1.x` is frozen rollback and
migration evidence while consumers cut over. Reconciliation changes require
separate worktrees, validation, commits, and linked pull requests; the canonical
`main` PR owns closing only after downstream integration and branch-specific
release machinery have retired. Never merge histories wholesale or share
generated output between worktrees. Branch ownership, reconciliation linkage,
conflict handling, and release safety rules are in
[`docs/RELEASE_LINES.md`](docs/RELEASE_LINES.md).

Open changes through a pull request whose title uses Conventional Commits
style. Preserve nearby `LICENSE` files and update attribution whenever an asset
is added, replaced, renamed, or moved. Do not assume a neighboring asset's
license applies without evidence.

Run `python3 tools/validate.py` before submitting a change. Generated collection
output is ignored and must not be committed.
