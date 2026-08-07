# Content architecture

The content repository owns authored world data and the deterministic tooling
that validates and collects it. It does not own the server's runtime loaders,
the client's streamed state, or standalone editor/checker implementations.

The source-to-runtime flow is:

1. authors change maps, archetypes, interfaces, scripts, and adjacent attribution;
2. `tools/content_catalog` assigns stable domain-qualified identities and checks
   cross-references;
3. `tools/validate.py` runs catalog, grammar-contract, corpus, collection, and
   licensing checks without modifying authored sources; and
4. `tools/build_runtime.py` creates an isolated runtime tree and digest manifest
   below `build/` or another explicit output path.

Stable identity ownership and rename/removal policy are documented in
[`CONTENT_IDENTITIES.md`](CONTENT_IDENTITIES.md). The complete legacy ADS grammar
and load-mode inventory, producer/consumer survey, versioned interchange schemas,
and byte-preserving parity corpus are documented in
[`CONTENT_GRAMMAR_CONTRACTS.md`](CONTENT_GRAMMAR_CONTRACTS.md). Those contracts
characterize the external server and checker boundaries that a future shared
lossless implementation must satisfy; they do not transfer implementation
ownership into this repository.

Generated runtime files are outputs, never authored sources. Exploratory reports
from `tools/world_content_audit.py` are review artifacts, not another identity or
grammar authority. A new loader, writer, checker, collector, or analyzer must use
the existing catalog and versioned contract boundaries instead of introducing a
duplicate parser or inventory.
