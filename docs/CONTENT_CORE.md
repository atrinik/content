# Lossless content core

`tools/content_core` is the production parser and targeted writer for legacy
Atrinik maps and archetypes. It keeps the original bytes as the serialization
authority while exposing typed, source-located semantic views derived from
`schemas/authored-content-v1/field-metadata.json`. It does not import the legacy
contract inspector or either syntax prototype; those remain independent parity
oracles.

## Guarantees and limits

An unchanged document serializes to the exact input bytes, including comments,
custom records, message bodies, nesting, multipart separators, record order,
line endings, trailing whitespace, and a missing final newline. Every node and
property has a half-open byte span. Standard property values are typed from the
authoritative field metadata; extension records retain a stable custom ID and
their raw value.

Input is strict UTF-8 without NUL. The shared fail-closed limits bound source
bytes, lines, line length, comments, message bodies, properties, nodes, and
nesting. The parser reports legacy compatibility diagnostics and additional
typed-value or schema-limit failures. A document is valid only when it has no
error-severity diagnostics.

`ProjectIndex` caches parsed documents by modification time and size, supports
explicit invalidation, and exposes deterministic lookup through the existing
stable content catalog. It does not create a second asset or identity index.

## Headless CLI

The CLI contract version is reported by `--version`. Machine output is
deterministic JSON when `--json` is present.

```sh
tools/atrinik-content --version
tools/atrinik-content --root . inspect maps/world_0_0 --json
tools/atrinik-content --root . validate arch/monsters/example.arc --json
tools/atrinik-content --root . diff arch/a.arc arch/b.arc --semantic --json
tools/atrinik-content --root . catalog search --kind archetype --text goblin --limit 20 --json
tools/atrinik-content --root . apply --patch build/change.json --json
tools/atrinik-content --root . apply --patch build/change.json --apply --json
```

`inspect` returns typed nodes, stable per-parse handles, node fingerprints,
source spans, comments, and common diagnostics. `validate` uses the same result
and exits nonzero for invalid content. `diff` compares ordered typed trees while
ignoring only comments, line-ending style, and trailing whitespace. `catalog
search` returns bounded stable catalog entries.

Exit status `0` is success, `1` is a semantic difference, `3` is invalid syntax
or encoding, `4` is a stale precondition or concurrent change, `5` is a safety
refusal, `6` is an I/O publication failure, and `7` is an invalid JSON contract
or other schema error.

## Transaction boundary

The schemas under `schemas/content-core-v1/` version inspection, catalog-search,
transaction, and transaction-result JSON. A transaction lists 1 to 64 sorted,
unique files and at most 10,000 primitive operations in total. Supported
operations are `set-property`, `unset-property`, `add-object`, and
`remove-object`.

Every file supplies the SHA-256 of its exact starting bytes. Every existing
node target also supplies the fingerprint returned by `inspect`. The core first
checks every path, digest, fingerprint, operation, source document, and complete
result document in memory. A stale or invalid member therefore prevents all
writes. Unknown standard fields, reserved fields without a legacy spelling,
wrong contexts, ambiguous duplicate properties, overlapping edits, and invalid
typed values fail closed.

`apply` is a dry run unless `--apply` is explicit. Publication creates a staged
file and backup in each target's directory, flushes content, preserves file
mode, rechecks every digest, and then uses same-directory atomic replacement.
If publication fails, already replaced files are restored and all temporary
files are removed. No portable filesystem primitive can make several files one
crash-atomic unit; callers must still recover from machine loss between
individual replacements, but handled process and I/O failures roll back the
whole transaction.

Writes require the Atrinik authored-source markers and are allowlisted to
existing regular, non-symlink `arch/*.arc` and `maps/` files. Paths containing
reserved build, generated, collected, packaged, runtime, distribution, or
server-state components are refused. Collected runtime trees and mutable server
state lack the source markers and are therefore not writable through the core.

## Consumer migration

`tools/world_content_audit.py` is the first migrated consumer. Its map and
archetype traversal adapts the common `Document` and `Node` model back to the
audit's established report shape. The dedicated regression test locks that
shape while the full corpus parity test independently compares all 14 grammar
fixtures with the legacy characterization expectations.
