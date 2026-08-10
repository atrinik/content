# Content release lines

`main` is the forward authoring line for the replacement stack. `1.x` is the
maintained classic-content line consumed only by `atrinik/classic` client,
editor, and server. Both descend from `v1.8.1` commit
`01b1fdb65c2243df4bafe9c8109fc93229df0121`; the branch split changes no file's
license or attribution.

## Choosing a target

- Assess every issue-driven fix against both `main` and `1.x`; a fix discovered
  on `1.x` must also reach `main` whenever compatible.
- Use `1.x` for compatible Classic-maintenance changes, including shared
  authored-content defects and Classic-only compatibility, security,
  attribution, or data-loss fixes that work with its ADS/Python consumers.
- Use `main` for replacement schemas, compiled artifacts, content-toolkit
  adoption, and forward authoring.
- Compatible shared fixes normally ship to both lines through separate
  worktrees, validation runs, commits, and linked pull requests. Preserve the
  original author and explain any conflict resolution independently.
- For paired delivery, the canonical `main` pull request is the only one that
  closes the issue; its `1.x` companion links both the issue and canonical pull
  request without using a closing keyword.
- A single-line exception must record explicit evidence and rationale
  explaining why the other line is unaffected or incompatible; its sole
  applicable pull request is canonical.
- Never merge branches wholesale or share generated output between worktrees.
- Identify a companion as a `backport to 1.x` when it originates on `main`, or
  a `forward-port to main` when it originates on `1.x`, and link the source
  pull request in its body. An ambiguous destination or incomplete attribution
  record blocks the change.

Every `1.x` pull request runs the stable `Content validation` and
`Conventional PR title` checks. Direct pushes, force pushes, deletion, and
nonlinear history are prohibited by organization rules. Builds use the
wrapper's distinct `content-1x` checkout and never share output with `content`.

## Releases

`release-line.txt` is `2.0` on `main` and `1.x` on branch `1.x`.
Validation treats either value appearing on the wrong branch as a release
boundary defect.

Semantic-release treats `1.x` as maintenance range `1.x` on channel `1.x` and
uses `vMAJOR.MINOR.PATCH` tags. `main` published `v1.9.0` after the `v1.8.1`
fork and owns that version permanently, so the maintenance line is bounded to
`>=1.8.1 <1.9.0` even though `main` has since established the 2.x replacement
line. The one exact analyzer rule for the historical `feat(release)` bootstrap
commit permitted `v1.8.2` without weakening normal feature or breaking-change
classification. Published releases and dry runs must remain in that range on
channel `1.x`.

Classic releases carry source branch/commit, content and artifact formats,
compatible classic versions, consumer modules, checksums, and exact license
digests. They set `replacement_ready` and `replacement_toolkit_package` false;
main-side tooling must reject them as replacement inputs.
