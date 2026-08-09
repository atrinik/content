# Content release lines

`main` is the forward authoring line for the replacement stack. `1.x` is the
maintained classic-content line consumed only by `atrinik/classic` client,
editor, and server. Both descend from `v1.8.1` commit
`01b1fdb65c2243df4bafe9c8109fc93229df0121`; the branch split changes no file's
license or attribution.

## Choosing a target

- Use `1.x` only for a classic compatibility, security, attribution, or
  data-loss fix that works with the classic ADS/Python consumer contract.
- Use `main` for replacement schemas, compiled artifacts, content-toolkit
  adoption, and forward authoring.
- When a fix applies to both, open two linked pull requests. Do not merge one
  branch wholesale into the other and do not copy generated output. Preserve
  the original author and explain any conflict resolution independently.
- Label the first change `backport-1.x` when it originates on `main`, or
  `forward-port-main` when it originates on `1.x`. Add `security` or
  `data-loss` when expedited review is required. An ambiguous destination or
  an incomplete attribution record blocks the change.

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
