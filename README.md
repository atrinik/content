# Atrinik content

This repository owns Atrinik's authored archetypes, maps, editor material, and
the collection tools that turn those sources into server runtime input.

The content has heterogeneous licensing. `arch/COPYING`, `maps/COPYING`, and
the nearest `LICENSE` file for an asset are authoritative; the repository does
not apply one blanket license to every file. Releases preserve those notices
and include a machine-readable digest manifest.

Build and validate a runtime tree without modifying authored sources:

```sh
python3 tools/build_runtime.py --output build/runtime
python3 tools/validate.py
```

The result contains collected files under `lib/`, compiled map interfaces and
authored maps under `maps/`, attribution files under `attribution/`, and
`manifest.json` with the SHA-256 of every packaged file.

The typed content catalog defines stable identities and validates authored
cross-references before collection. See
[`docs/CONTENT_IDENTITIES.md`](docs/CONTENT_IDENTITIES.md) for its commands,
source-of-truth table, and rename/removal policy.
