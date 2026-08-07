# Archetype and media guidance

- This guide applies below `arch/`. The repository-root guide remains in force.
- Preserve archetype object structure, inheritance, clone behavior, face and
  animation references, material flags, weights, values, and gameplay stats.
  A cosmetic edit must not silently alter behavior.
- Keep identifiers stable and unique in the content catalog. Display names and
  file positions are not persistent identities.
- Keep graphics and animation references case-correct and portable. Retain
  source attribution and the narrowest applicable license beside imported or
  transformed assets.
- When moving or renaming a resource, update all archetype, animation, map,
  artifact, treasure, interface, and script consumers in the same change.
- Run the root validator and isolated runtime build. Inspect the focused catalog
  diagnostics for every touched archetype or media identifier.
- Update this guide with any major archetype or media rework that changes these
  ownership, reference, licensing, layout, or validation contracts.
