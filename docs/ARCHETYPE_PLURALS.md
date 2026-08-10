# Reviewed archetype plural vocabulary

Every canonical `archetype:<Object ID>` has one explicit, non-empty `name_pl`.
The authored vocabulary is
[`tools/archetype-plurals-v1.json`](../tools/archetype-plurals-v1.json), keyed
by stable archetype ID rather than display text or source position. Its reviewed
SHA-256 is
`6c4eede454e239911049bb87c9ce5f96aeb328d0d11b6d7d9468ffb8c9569660`.

The manifest records the expected effective singular, object type, approved
plural, and review classification for all 3,559 definitions. It includes the
53 definitions that use their Object ID as the effective singular. The reviewed
baseline has 3,506 explicit singular names, 1,083 distinct effective singulars,
1,354 archetype files, 225 multipart continuations, and nine nested objects.
Multipart continuations and nested objects are deliberately excluded.

`tools/archetype_plurals.py` resolves definitions through the content catalog
and parses them with the lossless content core. `propose` is only a review aid;
it does not authorize a migration. The committed manifest records the completed
per-ID review, including irregular and compound nouns, already-plural and mass
nouns, proper names, spell/action labels, all internal controllers, and every
Object-ID fallback.

The migration is bound to the reviewed `main` and `1.x` baseline SHAs. It
pins the reviewed manifest digest and rejects source-tree, catalog, singular,
type, duplicate, partial, or existing-value drift. Every apply prepares and
dry-runs all deterministic batches of at most 64 files before one
migration-wide publication; a failure in any later batch rolls back all prior
replacements. Migration and recovery previews are stdout-only: `--output`
requires `--apply`, preserving their zero-write guarantee. A fully satisfied
rerun is a no-op.

```sh
python3 tools/archetype_plurals.py inventory --root .
python3 tools/archetype_plurals.py migrate --root .
python3 tools/archetype_plurals.py migrate --root . --apply
python3 tools/archetype_plurals.py audit --root .
python3 tools/archetype_plurals.py audit-source-delta --root .
```

The source-delta audit proves that the archetype corpus differs from the
reviewed branch baseline only by its 3,559 approved `name_pl` additions. The
semantic audit permanently requires exactly one matching plural on every
canonical definition and rejects plurals on the 234 excluded multipart or
nested objects. `python3 tools/validate.py` runs the permanent semantic audit
and verifies that runtime collection preserves every authored `name_pl` line
byte-for-byte. The baseline-bound source-delta audit above is separate one-time
delivery evidence so it does not reject legitimate future archetype edits.
Ordinary migration rejects a partial corpus. If a process or host terminates
outside the transaction rollback handler, `recover` first verifies that the
partial baseline diff contains only exact reviewed plural additions, then
removes those additions. A durable ignored journal also identifies transaction
stage/backup files created after publication began, so recovery removes only
migration-owned artifacts and preserves anything that predates or runs outside
the journal. Each operation is cross-process serialized, and its journal token
is embedded in every owned artifact name.
If the content core reports an incomplete rollback, both its remaining backup
artifacts and the ownership journal are retained for explicit recovery.
Recovery is dry-run-first and safely repeatable after another interruption;
rerun the migration only after recovery reaches the reviewed baseline.

```sh
python3 tools/archetype_plurals.py recover --root .
python3 tools/archetype_plurals.py recover --root . --apply
```

Cross-line review compares each branch's independently resolved inventory:

```sh
python3 tools/archetype_plurals.py compare --root . \
  --other-root /absolute/path/to/the/other/content/worktree \
  --output tools/archetype-plurals-cross-line-v1.json
```

At the reviewed baselines all 3,559 IDs, singulars, types, and approved plurals
are shared, with no branch-only rows or differences. The committed comparison
is machine-readable proof of that result. Comparison verifies the `main` and
`1.x` checkout identities and both baseline-bound source deltas before labelling
the result, so same-root or swapped inputs fail closed.

## Classic consumer gate

The `1.x` runtime collection preserves every authored plural. Published
`atrinik/classic` release
[`v5.10.1`](https://github.com/atrinik/classic/releases/tag/v5.10.1) is the
first release containing `name_pl` loader, server, and client support, so
`contracts/release-lines/classic-1x.json` records `>=5.10.1 <6.0.0` as the
truthful compatibility boundary. The completed consumer gate is tracked by
[`atrinik/classic#63`](https://github.com/atrinik/classic/issues/63).
