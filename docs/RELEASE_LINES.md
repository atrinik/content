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
as a patch by an exact analyzer rule; this permitted the first maintenance
release at `v1.8.2`. Eight feature commits merged before the patch-only
pull-request policy are also matched by exact type, scope, and subject rules:
colored-light authoring (#64), the Incuna Sam objective (#63), effective
light-source auditing (#67), the Incuna apartment flow (#112), fire-fixture
lighting (#115), crystal-light ownership (#116), the Rockforge teleporter glow
(#117), and toxic-pool lighting (#118). These bounded recovery rules cannot
classify a different feature subject as a patch.

The `Conventional PR title` check rejects every new `feat` or breaking title
whose base is `1.x`, while leaving `main` feature and breaking behavior
unchanged. Future `1.x` changes are maintenance fixes, not features. Published
releases and dry runs must remain in `>=1.8.1 <1.9.0` on channel `1.x`. The
GitHub release plugin deliberately disables its failure-issue hook. Release
failures remain visible in the workflow log, and an issue-creation or label
validation failure cannot obscure the originating Semantic Release error.

The release has three integrity layers:

- the source archive preserves the complete branch content and notices;
- the runtime archive contains classic-collected content plus `manifest.json`;
- `SHA256SUMS` binds both archives.

The runtime manifest names repository, branch, exact commit, formats, compatible
classic release range, consumer modules, replacement exclusion, every file
digest, and every packaged license/attribution digest. A consumer must reject a
manifest whose branch is not `1.x`, whose `replacement_ready` flag is not
false, or whose commit/checksum does not match the pinned release.

## Machine-readable parity ledger

`contracts/release-lines/parity-ledger.json` accounts for every commit after
the `v1.8.1` fork through immutable, line-specific horizons. Its Draft 2020-12
schema is `contracts/release-lines/parity-ledger.schema.json`; the repository's
dependency-free contract validator checks the schema before relational ledger
checks run.

An outcome owns every listed source and destination commit exactly once. A
single outcome can contain more than one source or destination commit when a
release line intentionally split or combined delivery. `exact` means the
stable patches are identical, `equivalent` means reviewed branch-native
integration produces the same intended result, `exempt` records a narrow
single-line product, and `pending` is reserved for undelivered work. Delivered
horizons reject pending outcomes. Equivalent and exempt outcomes must carry an
evidence-backed rationale, affected domains, owning issue and pull requests,
immutable commit coordinates, and prerequisites.

The ledger also lists every intentional resulting-tree difference explicitly.
Authored paths remain authored-domain records even when their serialized bytes
differ; in particular, `maps/light-source-review.json` is never release-control
maintenance. The two forcefield archetypes are equivalent because their field
values match independent of order. Replacement provenance and Classic-only
release/runtime products use narrow exemptions. Renderer evidence, capture
manifests, proof scenes, mutable state, and generated output are forbidden.

Run the local, network-free ledger validation from either branch:

```sh
python3 tools/release_line_parity.py --json
```

The terminal plan starts in `prepublication` state while its four pull request
identities are being allocated. Before any terminal merge it must become
`declared`, with exactly two commits per line in the order #137 then #139 and
the exact changed-path set for each ordinal. The horizons are immutable after
that declaration. Any missing, extra, reordered, missing-path, or
out-of-allowlist commit invalidates the declaration and requires a new horizon.
Actual squash SHAs are bound durably to the declared ordinals after merge; no
commit is required to contain its own SHA.

## Semantic cross-line audit

After both terminal candidates exist, compare their clean local checkouts with
an explicit opposite root:

```sh
python3 tools/release_line_parity.py \
  --root /path/to/content-main \
  --other-root /path/to/content-1x \
  --candidate-terminal \
  --json
```

The candidate flag relaxes only the final squash-subject binding, which GitHub
adds at merge. It still requires the declared horizon, exact two-commit suffix,
ordinal order, and exact changed-path set. At merged tips omit that flag; every
suffix commit must then bind the declared pull request in its subject.

The audit is local, deterministic, network-free, and read-only. It validates
both ledger copies and their complete post-fork histories, proves every
`exact` outcome with stable patch IDs, compares content-catalog definitions and
references through stable identities, and classifies the complete tracked-tree
delta in both directions. An exception that no longer differs is stale and
fails, just as an unclassified addition, removal, or value change fails.

Shared authored ADS is parsed through the lossless content core. Field records
are compared as typed multisets while object and child order remains
significant, so the two forcefield files prove equal despite harmless field
serialization order. An authored `equivalent` exception must pass that semantic
comparison; consumer-specific authored differences instead require an explicit
authored-domain exemption and rationale. Generated renderer evidence and
capture state remain outside both the ledger and the audit.
