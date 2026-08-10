# Content release lines

`main` is the forward authoring line for the replacement stack. `1.x` is the
maintained classic-content line consumed only by `atrinik/classic` client,
editor, and server. Both descend from `v1.8.1` commit
`01b1fdb65c2243df4bafe9c8109fc93229df0121`; the branch split changes no file's
license or attribution.

## Choosing a target

- Assess every issue-driven authored-content fix against both `main` and `1.x`;
  a fix discovered on `1.x` must also reach `main` whenever compatible.
- Use `1.x` for compatible Classic-maintenance changes, including shared
  authored-content defects and Classic-only compatibility, security,
  attribution, or data-loss fixes that work with its ADS/Python consumers.
- Use `main` for compatible shared authored-content defects and for replacement
  schemas, compiled artifacts, content-toolkit adoption, and forward authoring.
- Compatible shared fixes normally ship to both lines through separate
  worktrees, validation runs, commits, and linked pull requests. Preserve the
  original author and explain any conflict resolution independently.
- For paired delivery, the canonical `main` pull request is the only one that
  closes the issue; its `1.x` companion links both the issue and canonical pull
  request without using a closing keyword.
- A single-line exception must record explicit evidence and rationale
  explaining why the other line is unaffected or incompatible, such as
  replacement-only schemas or tooling, Classic-only formats or consumers,
  runtime incompatibility, or provenance or attribution constraints. The sole
  applicable pull request is canonical: a `main` pull request uses a closing
  keyword; a `1.x` pull request links without one, and the issue is closed
  manually after merge.
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

Semantic-release treats `1.x` as maintenance range `1.x` on channel `1.x` and
uses `vMAJOR.MINOR.PATCH` tags. `main` published `v1.9.0` after this branch's
`v1.8.1` fork and owns that version permanently, so the maintenance line is
bounded to `>=1.8.1 <1.9.0` even though `main` has since established the 2.x
replacement line. The historical `feat(release)` bootstrap commit is classified
as a patch by one exact analyzer rule; this permits the first maintenance
release at `v1.8.2` without weakening normal feature or breaking-change
classification. Future `1.x` changes are maintenance fixes, not features.
Published releases and dry runs must remain in `>=1.8.1 <1.9.0` on channel
`1.x`.

The release has three integrity layers:

- the source archive preserves the complete branch content and notices;
- the runtime archive contains classic-collected content plus `manifest.json`;
- `SHA256SUMS` binds both archives.

The runtime manifest names repository, branch, exact commit, formats, compatible
classic release range, consumer modules, replacement exclusion, every file
digest, and every packaged license/attribution digest. A consumer must reject a
manifest whose branch is not `1.x`, whose `replacement_ready` flag is not
false, or whose commit/checksum does not match the pinned release.
