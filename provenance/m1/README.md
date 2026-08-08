# M1 clean-room evidence

This directory is the branch-aware, fail-closed evidence boundary for the
clean-room replacement. It is pinned to `atrinik/content@v1.8.1` commit
`01b1fdb65c2243df4bafe9c8109fc93229df0121`, which is both the `main`
baseline and the immutable fork point of maintained branch `1.x`.

`python-behaviors.jsonl` inventories all 177 Python files at that revision.
Each row carries bytes and complete-history evidence, the identical `1.x`
baseline coordinate, static observations (not copied implementation), one
replacement owner and migration class, an issue and milestone, ambiguity, and
an independently phrased acceptance scenario. Runtime and map-local rows are
separate from offline tooling and test/mocks. Assignment does not authorize
copying GPL Python, and no replacement row permits a Python compatibility
plugin.

`materials.json` demonstrates every required provenance outcome: two sole
Zoey Rose machine contracts admitted through the exact historical MIT grant,
a compatible third-party painting, a transformed painting retaining its base
terms, a content-data fixture kept outside MIT packages, and one of the 526
license-unmatched visuals explicitly blocked. The package allowlists are exact
ID/digest projections; an inventory or historical license statement is never
implicit permission.

Regenerate and validate only from a complete, non-shallow checkout:

```sh
python3 tools/m1_foundations.py generate --root .
python3 tools/m1_foundations.py validate --root .
```

Later `1.x` maintenance is compared against these exact rows. A branch-only
change must create a new evidence row or explicit exclusion; it never silently
widens replacement scope or changes the historical file's terms.
