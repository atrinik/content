# Content release lines

`main` is the sole authored and released content source. This `1.x` branch is
immutable rollback and migration evidence, not an authored source, maintenance
line, or release channel. Both descend from `v1.8.1` commit
`01b1fdb65c2243df4bafe9c8109fc93229df0121`; the branch split changes no file's
license or attribution.

## Choosing a target

All authored defects, Classic compatibility, schemas, compiled artifacts,
content-toolkit adoption, and forward authoring target `main`. Do not deliver
changes to `1.x` or restore a maintenance channel. Emergency recreation or
maintenance requires a new explicit organization-owner decision and restored
governance. Until exact deletion, branch validation and title policy remain to
protect the frozen ref.

## Releases

Semantic Release is retired on this branch. The final rollback release is
`v1.8.19@566bd25f78b80b08d5f75f4b02017ab2429204db`. Its tag, release,
source/runtime archives, `SHA256SUMS`, manifests, licenses, and attribution are
immutable recovery evidence. No tag, release, or asset is moved, replaced, or
deleted during retirement.

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

The terminal plan is `declared` with exactly three squash commits per line:
#137, then #139, then the release-line retirement in #166. Each line preserves
its immutable pre-terminal horizon and the exact changed-path set for every
ordinal. Any missing, extra, reordered, missing-path, or out-of-allowlist commit
invalidates the declaration and requires a new horizon. Actual squash SHAs are
bound durably to the declared ordinals after merge; no commit is required to
contain its own SHA.

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
adds at merge. It still requires the declared horizon, exact three-commit suffix,
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
