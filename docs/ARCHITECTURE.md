# Content architecture

The content repository owns authored world data and the deterministic tooling
that validates and collects it. It does not own the server's runtime loaders,
the client's streamed state, or standalone editor/checker implementations.

The source-to-runtime flow is:

1. authors change maps, archetypes, interfaces, scripts, and adjacent attribution;
2. `tools/content_catalog` assigns stable domain-qualified identities and checks
   cross-references;
3. `schemas/authored-content-v1/source.json` types the closed field surface and
   generates shared loader/compiler, editor, and logical-document metadata;
4. `tools/content_core` provides the byte-lossless production parser, typed
   source-located views, project index, and transaction-safe targeted writer;
5. `tools/validate.py` runs catalog, schema, grammar-contract, corpus, collection,
   and licensing checks without modifying authored sources; and
6. `tools/build_runtime.py` creates an isolated runtime tree and digest manifest
   below `build/` or another explicit output path.

Stable identity ownership and rename/removal policy are documented in
[`CONTENT_IDENTITIES.md`](CONTENT_IDENTITIES.md). The complete legacy ADS grammar
and load-mode inventory, producer/consumer survey, versioned interchange schemas,
and byte-preserving parity corpus are documented in
[`CONTENT_GRAMMAR_CONTRACTS.md`](CONTENT_GRAMMAR_CONTRACTS.md). Those contracts
characterize the external server and checker boundaries that a future shared
lossless implementation must satisfy. The production implementation now lives
in `tools/content_core`; the characterization inspector remains a parity oracle
and is not imported by that core.

The authoritative typed field and logical-document contract is documented in
[`CONTENT_SCHEMA.md`](CONTENT_SCHEMA.md). Its declarative source is checked
against the legacy grammar inventory and selected parser limits, and all other
schema files are deterministic generated projections. The grammar contract
continues to own compatibility observations; it is not a competing field
authority. Consumers must adopt the generated metadata instead of maintaining a
new hand-written field inventory.

The future typed authored surface is the strict JSONC dialect selected in
[`AUTHORED_SYNTAX_DECISION.md`](AUTHORED_SYNTAX_DECISION.md). Its limits,
logical-ID independence from physical suffixes, explicit custom namespace,
comment/span requirements, representative measurements, and cross-language
adapter constraints are authoritative inputs to schema and lossless-core work.
The syntax prototypes and physical-record model remain evaluation/migration
oracles; they are not another production parser or content IR. The generated
logical schema defines the typed interchange shape, while the lossless core owns
production parsing and rewriting. Its CLI and transaction contracts are
documented in [`CONTENT_CORE.md`](CONTENT_CORE.md).

Generated runtime files are outputs, never authored sources. Exploratory reports
from `tools/world_content_audit.py` are review artifacts, not another identity or
grammar authority. Its map and archetype traversal uses the common core. A new
loader, writer, checker, collector, or analyzer must use the existing catalog,
lossless core, and versioned contract boundaries instead of introducing a
duplicate parser or inventory.
