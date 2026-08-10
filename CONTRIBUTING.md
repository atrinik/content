# Contributing

Assess every issue-driven authored-content fix against both `main` and `1.x`;
a fix discovered on `1.x` must also reach `main` whenever compatible.
Compatible shared fixes
normally ship to both lines through separate worktrees, validation runs,
commits, and linked pull requests. For paired delivery, the canonical `main`
pull request is the only one that closes the issue; its `1.x` companion links
both the issue and canonical pull request without using a closing keyword. A
single-line exception must record explicit evidence and rationale explaining
why the other line is unaffected or incompatible, such as replacement-only
schemas or tooling, Classic-only formats or consumers, runtime incompatibility,
or provenance or attribution constraints; its sole applicable pull request is
canonical. Never merge branches wholesale or share generated output between
worktrees. Branch ownership, port linkage, conflict
handling, and release safety rules are in
[`docs/RELEASE_LINES.md`](docs/RELEASE_LINES.md).

Open changes through a pull request whose title uses Conventional Commits
style. Preserve nearby `LICENSE` files and update attribution whenever an asset
is added, replaced, renamed, or moved. Do not assume a neighboring asset's
license applies without evidence.

Run `python3 tools/validate.py` before submitting a change. Generated collection
output is ignored and must not be committed.
